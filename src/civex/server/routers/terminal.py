from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from asyncio.subprocess import PIPE, STDOUT

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/terminal", tags=["terminal"])


class _LineBuffer:
    """Minimal line discipline: echoes printable chars, handles backspace and Enter."""

    def __init__(self) -> None:
        self._buf: bytearray = bytearray()

    def feed(self, data: bytes) -> tuple[list[bytes], bytes]:
        lines: list[bytes] = []
        echo = bytearray()
        for b in data:
            if b in (0x0D, 0x0A):          # Enter / CR
                echo.extend(b"\r\n")
                lines.append(bytes(self._buf) + b"\n")
                self._buf.clear()
            elif b in (0x7F, 0x08):         # Backspace / DEL
                if self._buf:
                    self._buf.pop()
                    echo.extend(b"\x08 \x08")
            elif 0x20 <= b < 0x7F:          # Printable ASCII
                self._buf.append(b)
                echo.append(b)
            elif b == 0x03:                 # Ctrl-C
                echo.extend(b"^C\r\n")
                self._buf.clear()
                lines.append(b"exit\n")
        return lines, bytes(echo)


@router.websocket("/ws")
async def terminal_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    env = {**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0", "NO_COLOR": "1"}

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        "from civex.cli.shell import run_shell; run_shell()",
        stdin=PIPE,
        stdout=PIPE,
        stderr=STDOUT,
        env=env,
    )

    buf = _LineBuffer()

    async def _read_proc() -> None:
        assert proc.stdout
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    async def _write_proc() -> None:
        assert proc.stdin
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                raw: bytes = msg.get("bytes") or (msg.get("text") or "").encode()
                if not raw:
                    continue
                lines, echo = buf.feed(raw)
                if echo:
                    await websocket.send_bytes(echo)
                for line in lines:
                    proc.stdin.write(line)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, Exception):
            pass

    read_task = asyncio.create_task(_read_proc())
    write_task = asyncio.create_task(_write_proc())

    await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)

    for task in (read_task, write_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    with contextlib.suppress(ProcessLookupError, OSError):
        proc.kill()
        await proc.wait()

    with contextlib.suppress(Exception):
        await websocket.send_bytes(b"\r\n\x1b[2m[session ended]\x1b[0m\r\n")
        await websocket.close()
