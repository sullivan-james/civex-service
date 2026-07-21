"""RPC-backed plugin context: the out-of-process equivalent of civex-service's
in-process `WorkflowContext`, offering the same CRUD-shaped capability
surface but implemented by sending an `rpc_call` frame and blocking for the
matching `rpc_result`/`error` response. Every method takes an explicit
target (record id, dataset name, ...) -- none of them special-case "the
record that triggered this workflow"; get_context_record()/
get_context_dataset() are how a plugin learns that id in the first place,
since (unlike WorkflowContext) Ctx has no ambient `.record`/`.dataset`.

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
    encode_binary,
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

    def _call_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """All CRUD-shaped methods below (records beyond the trigger,
        files-as-create, schemas, collections) go over this one generic RPC
        method rather than growing RpcMethod one literal at a time -- see
        protocol.py's note above CAPABILITIES."""
        return self._call("call_tool", {"tool": tool, "args": args})

    def get_context_record(self) -> dict[str, Any]:
        """The record that triggered this workflow step. `Ctx` has no
        ambient `.record`/`.dataset` fields the way in-process
        WorkflowContext does -- this (and get_context_dataset()) is the
        only way an out-of-process plugin learns what triggered it."""
        result = self._call_tool("get_context_record", {})
        return result["record"]

    def get_context_dataset(self) -> dict[str, Any]:
        result = self._call_tool("get_context_dataset", {})
        return result["dataset"]

    def get_file(self, sha256: str) -> bytes:
        result = self._call("get_file", {"sha256": sha256})
        return decode_binary(result)

    def store_file(self, data: bytes, filename: str) -> dict[str, Any]:
        result = self._call_tool(
            "store_file",
            {"data": encode_binary(data, self._scratch_dir), "filename": filename},
        )
        return result["file"]

    def update_record(self, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._call("update_record", {"record_id": record_id, "data": data})

    def create_record(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        context_record_id: str | None = None,
    ) -> dict[str, Any]:
        """`context_record_id`, when omitted, defaults host-side to
        get_context_record()'s id -- see WorkflowContext.create_record's
        docstring for why it isn't called parent_record_id."""
        return self._call(
            "create_record",
            {
                "dataset_name": dataset_name,
                "schema_name": schema_name,
                "data": data,
                "context_record_id": context_record_id,
            },
        )

    def get_record(self, record_id: str) -> dict[str, Any]:
        result = self._call_tool("get_record", {"record_id": record_id})
        return result["record"]

    def find_records(
        self,
        dataset_name: str,
        schema_name: str | None = None,
        parent_record_id: str | None = None,
        filters: list[str] | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        result = self._call_tool(
            "find_records",
            {
                "dataset_name": dataset_name,
                "schema_name": schema_name,
                "parent_record_id": parent_record_id,
                "filters": filters,
                "search": search,
                "limit": limit,
                "offset": offset,
            },
        )
        return result["records"]

    def delete_record(self, record_id: str) -> None:
        self._call_tool("delete_record", {"record_id": record_id})

    def get_schema(self, name: str) -> dict[str, Any]:
        result = self._call_tool("get_schema", {"name": name})
        return result["schema"]

    def list_schemas(self) -> list[dict[str, Any]]:
        result = self._call_tool("list_schemas", {})
        return result["schemas"]

    def get_collection(self, name: str) -> dict[str, Any]:
        result = self._call_tool("get_collection", {"name": name})
        return result["collection"]

    def list_collections(self) -> list[dict[str, Any]]:
        result = self._call_tool("list_collections", {})
        return result["collections"]

    def commit(self) -> None:
        self._call("commit", {})
