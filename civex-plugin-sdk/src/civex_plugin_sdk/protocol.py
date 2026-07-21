"""Newline-delimited JSON-RPC-over-stdio wire protocol.

One JSON object per line, in both directions over a single stdin/stdout
pair. The host sends `describe`/`run` requests and `rpc_result`/`error`
responses to a plugin's stdin; the plugin sends `describe_result`/`result`/
`error`/`log` frames and `rpc_call` requests over its (fd-duped, see
`io.isolate_stdout`) private stdout.

Binary payloads (e.g. get_file results) are base64-inlined for small/medium
sizes; above BINARY_INLINE_THRESHOLD they're written to a shared scratch
path instead, and the frame carries that path rather than the bytes.
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

RpcMethod = Literal["get_file", "update_record", "create_record", "commit"]

CAPABILITIES: tuple[RpcMethod, ...] = (
    "get_file",
    "update_record",
    "create_record",
    "commit",
)


class DescribeRequest(BaseModel):
    type: Literal["describe"] = "describe"


class DescribeResult(BaseModel):
    type: Literal["describe_result"] = "describe_result"
    id: str
    name: str
    category: str = "general"
    capabilities: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    type: Literal["run"] = "run"
    inputs: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    type: Literal["result"] = "result"
    outputs: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(BaseModel):
    code: str
    message: str


class ErrorFrame(BaseModel):
    type: Literal["error"] = "error"
    # Set when this frame is a response to a specific rpc_call; unset when
    # it's the top-level error for a "run" request.
    call_id: str | None = None
    error: ErrorPayload


class LogFrame(BaseModel):
    type: Literal["log"] = "log"
    stream: Literal["stdout", "stderr"] = "stdout"
    text: str


class RpcCall(BaseModel):
    type: Literal["rpc_call"] = "rpc_call"
    call_id: str
    method: RpcMethod
    params: dict[str, Any] = Field(default_factory=dict)


class RpcResult(BaseModel):
    type: Literal["rpc_result"] = "rpc_result"
    call_id: str
    result: dict[str, Any] = Field(default_factory=dict)


FRAME_TYPES: dict[str, type[BaseModel]] = {
    "describe": DescribeRequest,
    "describe_result": DescribeResult,
    "run": RunRequest,
    "result": RunResult,
    "error": ErrorFrame,
    "log": LogFrame,
    "rpc_call": RpcCall,
    "rpc_result": RpcResult,
}


def parse_frame(raw: dict[str, Any]) -> BaseModel:
    """Validate a raw decoded JSON object against its declared `type`."""
    frame_type = raw.get("type")
    model = FRAME_TYPES.get(frame_type)  # type: ignore[arg-type]
    if model is None:
        raise ValueError(f"Unknown frame type: {frame_type!r}")
    return model.model_validate(raw)


def new_call_id() -> str:
    return uuid.uuid4().hex


# Above this size, binary payloads are written to scratch instead of
# base64-inlined in the JSON frame.
BINARY_INLINE_THRESHOLD = 1_000_000  # 1 MB


def encode_binary(data: bytes, scratch_dir: Path | None = None) -> dict[str, Any]:
    if scratch_dir is None or len(data) <= BINARY_INLINE_THRESHOLD:
        return {"encoding": "base64", "data": base64.b64encode(data).decode("ascii")}
    scratch_dir.mkdir(parents=True, exist_ok=True)
    path = scratch_dir / f"{uuid.uuid4().hex}.bin"
    path.write_bytes(data)
    return {"encoding": "path", "path": str(path)}


def decode_binary(payload: dict[str, Any]) -> bytes:
    encoding = payload.get("encoding")
    if encoding == "base64":
        return base64.b64decode(payload["data"])
    if encoding == "path":
        return Path(payload["path"]).read_bytes()
    raise ValueError(f"Unknown binary encoding: {encoding!r}")
