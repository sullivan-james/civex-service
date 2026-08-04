"""Frame I/O: newline-delimited JSON reader/writer, plus the fd-dup stdout isolation trick that keeps stray print()/library output from corrupting the protocol stream.

The reader/writer are built on injected callables/iterators rather than
directly on sys.stdin/sys.stdout so they're unit-testable without real file
descriptors. `isolate_stdout()` is the thin real-fd wrapper used only by the
actual `serve()` entrypoint.

Not part of `civex_plugin_sdk.__all__` -- a plugin author writes `invoke()`
against `Plugin`/`Ctx` and never touches frames directly -- but civex's own
host-side subprocess runtime (`civex.plugins.subprocess_runtime`) imports
`FrameWriter`/`FrameReader` from here directly, to speak the same
newline-delimited-JSON protocol from the host end of the pipe. Treat this
module as internal-but-depended-upon rather than private: a breaking change
here breaks the host runtime, even though nothing in this package imports it
as a public name.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TextIO


class FrameWriter:
    """Sends one JSON object per line to an injected write callable."""

    def __init__(self, write: Callable[[str], None]) -> None:
        """Wrap an arbitrary `str -> None` sink as a frame writer.

        Args:
            write: Called once per frame with the encoded line (including
                the trailing newline). Injected rather than a stream
                directly so tests can pass a list-appending callable.
        """
        self._write = write

    def send(self, frame: dict[str, Any]) -> None:
        """Encode `frame` as one compact JSON line and write it."""
        self._write(json.dumps(frame, separators=(",", ":")) + "\n")

    @classmethod
    def for_stream(cls, stream: TextIO) -> "FrameWriter":
        """Build a `FrameWriter` that writes to `stream` and flushes after every frame.

        The flush matters: both sides of the pipe block on `next(reader)`
        for the next line, so a buffered write that never reaches the OS
        would deadlock the other side rather than merely delay it.
        """

        def write(line: str) -> None:
            stream.write(line)
            stream.flush()

        return cls(write)


class FrameReader:
    """Iterates decoded JSON frames from an injected line iterable, skipping blank lines."""

    def __init__(self, lines: Iterable[str]) -> None:
        """Wrap an arbitrary iterable of lines as a frame reader.

        Args:
            lines: Injected rather than a stream directly so tests can pass
                a plain list of lines.
        """
        self._lines: Iterator[str] = iter(lines)

    def __iter__(self) -> "FrameReader":
        """Return self -- `FrameReader` is its own iterator."""
        return self

    def __next__(self) -> dict[str, Any]:
        """Return the next non-blank line, decoded as JSON."""
        line = next(self._lines)
        while line.strip() == "":
            line = next(self._lines)
        return json.loads(line)

    @classmethod
    def for_stream(cls, stream: TextIO) -> "FrameReader":
        """Build a `FrameReader` that reads lines from `stream`."""
        return cls(stream)


def isolate_stdout() -> TextIO:
    """Duplicate the real stdout fd to a private fd, then redirect the public fd 1 to devnull so stray print()/library output can't corrupt the protocol stream.

    Must be called at the very start of serve(), before any plugin code
    runs.

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
    """Return an iterator over real stdin's lines, for `FrameReader.for_stream(sys.stdin)`'s caller to pass without importing `sys` directly."""
    return iter(sys.stdin)
