"""An app under a real server, for tests of the HTTP transport."""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any


@contextlib.contextmanager
def serve(app: Any, timeout: float = 5.0) -> Iterator[str]:
    """Run `app` under uvicorn on a free loopback port, on a thread, and yield
    its base URL (`http://127.0.0.1:<port>`); stop it on the way out."""
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the test server did not start in time")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
