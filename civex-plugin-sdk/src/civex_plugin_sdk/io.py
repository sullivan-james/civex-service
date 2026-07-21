"""Frame I/O: newline-delimited JSON reader/writer, plus the fd-dup stdout
isolation trick that keeps stray print()/library output from corrupting the
protocol stream.

The reader/writer are built on injected callables/iterators rather than
directly on sys.stdin/sys.stdout so they're unit-testable without real file
descriptors. `isolate_stdout()` is the thin real-fd wrapper used only by the
actual `serve()` entrypoint.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TextIO


class FrameWriter:
    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write

    def send(self, frame: dict[str, Any]) -> None:
        self._write(json.dumps(frame, separators=(",", ":")) + "\n")

    @classmethod
    def for_stream(cls, stream: TextIO) -> "FrameWriter":
        def write(line: str) -> None:
            stream.write(line)
            stream.flush()

        return cls(write)


class FrameReader:
    def __init__(self, lines: Iterable[str]) -> None:
        self._lines: Iterator[str] = iter(lines)

    def __iter__(self) -> "FrameReader":
        return self

    def __next__(self) -> dict[str, Any]:
        line = next(self._lines)
        while line.strip() == "":
            line = next(self._lines)
        return json.loads(line)

    @classmethod
    def for_stream(cls, stream: TextIO) -> "FrameReader":
        return cls(stream)


def isolate_stdout() -> TextIO:
    """Duplicate the real stdout fd to a private fd, then redirect the
    public fd 1 to devnull so any print()/library output a plugin author's
    code emits can't corrupt the protocol stream. Must be called at the very
    start of serve(), before any plugin code runs.

    Returns a line-buffered text file object wrapping the private fd; the
    SDK's own protocol writes (FrameWriter) go through this, never through
    sys.stdout. Both the subprocess and container tiers spawn this process
    with stdout captured (`subprocess.Popen(..., stdout=PIPE)` /
    `docker run -i`), so a plain fd-dup is invisible to the parent and
    identical across tiers -- the uniformity lives inside the child
    process, not in how the parent spawns it.
    """
    real_stdout_fd = os.dup(1)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull_fd, 1)
    os.close(devnull_fd)
    return os.fdopen(real_stdout_fd, "w", buffering=1)


def stdin_lines() -> Iterator[str]:
    return iter(sys.stdin)
