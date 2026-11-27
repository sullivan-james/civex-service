"""How much memory the file transfers of one process may hold at once.

One budget for the whole process, so uploads (and later downloads and pulls)
share it instead of each adding up its own windows. A unit of work (a part of a
big file, a pack's read buffer) takes its bytes from the budget before it is
read and gives them back when it is done; when the budget is spent, the next
unit waits. Nothing ever holds a whole large file: a file is read a part at a
time, and a larger spool goes to disk (`spool`).

Sizes (`CIVEX_SYNC_MEMORY_MB` sets the budget in MiB and wins over the rest):

- 128 MiB, with 16 MiB parts, 6 parts and 2 big files in flight; or
- 64 MiB, with 8 MiB parts, 4 parts and 2 big files in flight, on a machine
  with under 8 GiB of RAM (or any budget below 128 MiB).

Use `process_budget()` for the budget and `windows()` for the windows that go
with it; take bytes with `with budget.hold(n): ...`.
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator
from typing import IO

MiB = 1024 * 1024
DEFAULT_BUDGET_BYTES = 128 * MiB
SMALL_BUDGET_BYTES = 64 * MiB
SMALL_RAM_BYTES = 8 * 1024 * MiB
# A body held in memory up to this many bytes, then in a temp file.
SPOOL_BYTES = 4 * MiB


class TransferBudget:
    """A count of bytes that may be in hand at once. `acquire(n)` waits until
    n bytes are free (a request larger than the whole budget is charged the
    whole budget, so it can still go, alone) and answers what was charged;
    `release` gives that amount back."""

    def __init__(self, total: int) -> None:
        self.total = max(1, int(total))
        self._used = 0
        self.peak = 0
        self._cond = threading.Condition()

    @property
    def in_hand(self) -> int:
        with self._cond:
            return self._used

    def acquire(self, n: int) -> int:
        n = max(0, min(int(n), self.total))
        with self._cond:
            while self._used + n > self.total:
                self._cond.wait()
            self._used += n
            self.peak = max(self.peak, self._used)
        return n

    def release(self, n: int) -> None:
        with self._cond:
            self._used = max(0, self._used - n)
            self._cond.notify_all()

    @contextmanager
    def hold(self, n: int) -> Iterator[int]:
        charged = self.acquire(n)
        try:
            yield charged
        finally:
            self.release(charged)


@dataclass(frozen=True)
class TransferWindows:
    """How much goes at once, sized to go with the budget."""

    budget_bytes: int
    part_bytes: int  # the largest part of a big file asked for
    part_threads: int  # parts in flight, all files together
    large_files: int  # big files in flight
    packs: int  # packs of small files in flight

    @property
    def small(self) -> bool:
        return self.budget_bytes < DEFAULT_BUDGET_BYTES


def total_ram_bytes() -> int | None:
    """The machine's RAM, or None when it can't be told. Linux, macOS, Windows."""
    try:
        if sys.platform == "win32":

            class _Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong),
                    ("page_total", ctypes.c_ulonglong),
                    ("page_avail", ctypes.c_ulonglong),
                    ("virt_total", ctypes.c_ulonglong),
                    ("virt_avail", ctypes.c_ulonglong),
                    ("ext", ctypes.c_ulonglong),
                ]

            status = _Status()
            status.length = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return int(status.total)
            return None
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        # macOS and other Unix
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (OSError, ValueError, AttributeError, KeyError):
        return None


def budget_bytes(ram: int | None = None, environ: dict[str, str] | None = None) -> int:
    """The budget for this machine: `CIVEX_SYNC_MEMORY_MB`, else 128 MiB, or
    64 MiB under 8 GiB of RAM."""
    env = os.environ if environ is None else environ
    try:
        wanted = int(float(env.get("CIVEX_SYNC_MEMORY_MB", "")) * MiB)
    except ValueError:
        wanted = 0
    if wanted > 0:
        return max(MiB, wanted)
    ram = total_ram_bytes() if ram is None else ram
    if ram is not None and ram < SMALL_RAM_BYTES:
        return SMALL_BUDGET_BYTES
    return DEFAULT_BUDGET_BYTES


def windows_for(budget: int) -> TransferWindows:
    if budget >= DEFAULT_BUDGET_BYTES:
        return TransferWindows(budget, 16 * MiB, 6, 2, 4)
    return TransferWindows(budget, 8 * MiB, 4, 2, 2)


_lock = threading.Lock()
_budget: TransferBudget | None = None
_windows: TransferWindows | None = None


def process_budget() -> TransferBudget:
    global _budget, _windows
    with _lock:
        if _budget is None:
            total = budget_bytes()
            _budget, _windows = TransferBudget(total), windows_for(total)
        return _budget


def windows() -> TransferWindows:
    process_budget()
    assert _windows is not None
    return _windows


def reset(total: int | None = None) -> TransferBudget:
    """Start over (tests, and a host that sets its own size): a fresh budget
    of `total` bytes, or the machine's."""
    global _budget, _windows
    with _lock:
        total = budget_bytes() if total is None else total
        _budget, _windows = TransferBudget(total), windows_for(total)
        return _budget


def spool() -> IO[bytes]:
    """A body that is held in memory up to a few MiB and in a temp file past
    that, for what arrives faster than it can be put away."""
    return tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115
