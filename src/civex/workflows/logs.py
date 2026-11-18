"""What a workflow run prints, kept for its record: stdout, stderr and log
lines, without the web server's and database's own chatter. Shared by the
background drain and a trial run, so both keep the same log."""

from __future__ import annotations

import contextlib
import io
import logging

_NOISY_PREFIXES = (
    "sqlalchemy",
    "uvicorn",
    "fastapi",
    "httpx",
    "asyncio",
    "urllib3",
    "watchfiles",
    "h11",
)


class _WorkflowLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not any(record.name.startswith(p) for p in _NOISY_PREFIXES)


@contextlib.contextmanager
def capture_output():
    """Capture stdout, stderr, and non-noisy log records into a single buffer."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    handler.addFilter(_WorkflowLogFilter())
    root = logging.getLogger()
    prev_level = root.level
    root.addHandler(handler)
    root.setLevel(min(prev_level, logging.DEBUG))
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            yield buf
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)
