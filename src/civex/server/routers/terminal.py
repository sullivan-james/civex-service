from __future__ import annotations

import sys

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/terminal", tags=["terminal"])

if sys.platform == "win32":
    # pty/fcntl/termios are Unix-only; expose a stub that tells the client.
    @router.websocket("/ws")
    async def terminal_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("Terminal is not supported on Windows.\r\n")
        await websocket.close(code=1011, reason="unsupported platform")

else:
    import asyncio
    import contextlib
    import fcntl
    import json
    import os
    import pty
    import signal
    import struct
    import termios

    def _set_winsize(fd: int, rows: int, cols: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    @router.websocket("/ws")
    async def terminal_ws(websocket: WebSocket) -> None:
        await websocket.accept()

        pid, master_fd = pty.fork()
        if pid == 0:
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "xterm-256color"}
            try:
                os.execvpe(
                    sys.executable,
                    [
                        sys.executable,
                        "-c",
                        "from civex.cli.shell import run_shell; run_shell()",
                    ],
                    env,
                )
            finally:
                os._exit(1)

        _set_winsize(master_fd, 24, 80)
        loop = asyncio.get_event_loop()

        async def _read_pty() -> None:
            try:
                while True:
                    try:
                        data = await loop.run_in_executor(
                            None, os.read, master_fd, 4096
                        )
                    except OSError:
                        break
                    if not data:
                        break
                    await websocket.send_bytes(data)
            except Exception:
                pass

        async def _write_pty() -> None:
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    if msg.get("bytes") is not None:
                        os.write(master_fd, msg["bytes"])
                    elif msg.get("text") is not None:
                        try:
                            ctrl = json.loads(msg["text"])
                        except ValueError:
                            continue
                        if ctrl.get("type") == "resize":
                            rows = int(ctrl.get("rows", 24))
                            cols = int(ctrl.get("cols", 80))
                            _set_winsize(master_fd, rows, cols)
                            with contextlib.suppress(ProcessLookupError):
                                os.kill(pid, signal.SIGWINCH)
            except (WebSocketDisconnect, Exception):
                pass

        read_task = asyncio.create_task(_read_pty())
        write_task = asyncio.create_task(_write_pty())

        await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)

        for task in (read_task, write_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        with contextlib.suppress(ProcessLookupError, OSError):
            os.kill(pid, signal.SIGTERM)
        with contextlib.suppress(ChildProcessError):
            await loop.run_in_executor(None, os.waitpid, pid, 0)
        with contextlib.suppress(OSError):
            os.close(master_fd)

        with contextlib.suppress(Exception):
            await websocket.send_bytes(b"\r\n\x1b[2m[session ended]\x1b[0m\r\n")
            await websocket.close()
