"""RPC-backed plugin context: the out-of-process equivalent of civex-service's
in-process `WorkflowContext`, offering the same four capability methods but
implemented by sending an `rpc_call` frame and blocking for the matching
`rpc_result`/`error` response.

The protocol is strictly synchronous request/response with no interleaving,
so blocking on `next(reader)` for the next line is sufficient -- the host
must answer an rpc_call before sending anything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from civex_plugin_sdk.errors import RpcError
from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.protocol import (
    RpcCall,
    RpcMethod,
    RpcResult,
    decode_binary,
    new_call_id,
    parse_frame,
)


class Ctx:
    def __init__(
        self,
        writer: FrameWriter,
        reader: FrameReader,
        scratch_dir: Path | None = None,
    ) -> None:
        self._writer = writer
        self._reader = reader
        self._scratch_dir = scratch_dir

    def _call(self, method: RpcMethod, params: dict[str, Any]) -> dict[str, Any]:
        call_id = new_call_id()
        self._writer.send(
            RpcCall(call_id=call_id, method=method, params=params).model_dump()
        )
        raw = next(self._reader)
        frame = parse_frame(raw)
        if getattr(frame, "type", None) == "error":
            payload = frame.error  # type: ignore[attr-defined]
            raise RpcError(payload.message, code=payload.code)
        if not isinstance(frame, RpcResult) or frame.call_id != call_id:
            raise RpcError(f"unexpected response to rpc_call {method!r}: {raw!r}")
        return frame.result

    def get_file(self, sha256: str) -> bytes:
        result = self._call("get_file", {"sha256": sha256})
        return decode_binary(result)

    def update_record(self, data: dict[str, Any]) -> None:
        self._call("update_record", {"data": data})

    def create_record(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        parent_record_id: str | None = None,
    ) -> dict[str, Any]:
        return self._call(
            "create_record",
            {
                "dataset_name": dataset_name,
                "schema_name": schema_name,
                "data": data,
                "parent_record_id": parent_record_id,
            },
        )

    def commit(self) -> None:
        self._call("commit", {})
