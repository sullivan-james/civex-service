"""RPC-backed plugin context: the out-of-process equivalent of civex-service's in-process `WorkflowContext`.

Offers the same CRUD-shaped capability surface but implemented by sending an
`rpc_call` frame and blocking for the matching `rpc_result`/`error`
response. Every method takes an explicit target (record id, dataset name,
...) -- none of them special-case "the record that triggered this
workflow"; get_context_record()/get_context_dataset() are how a plugin
learns that id in the first place, since (unlike WorkflowContext) Ctx has no
ambient `.record`/`.dataset`.

The protocol is strictly synchronous request/response with no interleaving,
so blocking on `next(reader)` for the next line is sufficient -- the host
must answer an rpc_call before sending anything else.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from civex_plugin_sdk.errors import RpcError
from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.protocol import (
    ProgressFrame,
    RpcCall,
    RpcMethod,
    RpcResult,
    decode_binary,
    encode_binary,
    new_call_id,
    parse_frame,
)


class Ctx:
    """The handle `invoke()` receives for everything beyond `inputs`/`config`: records, files, schemas, and collections.

    Every method blocks on a single `rpc_call`/`rpc_result` round trip over
    `writer`/`reader` -- there is no batching or concurrency, so a plugin
    calling several `Ctx` methods pays one blocking round trip per call.
    """

    def __init__(
        self,
        writer: FrameWriter,
        reader: FrameReader,
        scratch_dir: Path | None = None,
    ) -> None:
        """Wrap the frame reader/writer pair `serve()`/`serve_container()` built for this run.

        Args:
            writer: Sends `rpc_call` frames to the host.
            reader: Blocks for the matching `rpc_result`/`error` response.
            scratch_dir: Where `store_file()` writes payloads too large to
                inline. `None` (the default) always inlines as base64.
        """
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
            # Carries the host's own classification through unchanged rather
            # than flattening every failed rpc_call to "rpc_error" -- a
            # capability_denied has to stay recognizable as one by the time
            # it reaches the job record.
            raise RpcError(
                payload.message, kind=payload.kind, retryable=payload.retryable
            )
        if not isinstance(frame, RpcResult) or frame.call_id != call_id:
            raise RpcError(f"unexpected response to rpc_call {method!r}: {raw!r}")
        return frame.result

    def _call_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Send a `call_tool` rpc_call for `tool` and return its result.

        All CRUD-shaped methods below (records beyond the trigger,
        files-as-create, schemas, collections) go over this one generic RPC
        method rather than growing RpcMethod one literal at a time -- see
        protocol.py's note above CAPABILITIES.
        """
        return self._call("call_tool", {"tool": tool, "args": args})

    def progress(
        self, done: float, total: float | None = None, message: str = ""
    ) -> None:
        """Say how far this run has got, for whoever is watching it.

        The civex app shows it in the status bar while the run lasts. Cheap
        (one line to the host, no answer), but there is no point in calling
        it more than a few times a second.

        Args:
            done: How much is done (items, bytes, ...).
            total: How much there is in all, or None if unknown.
            message: What it is doing now, e.g. "Reading sel_03.txt".
        """
        self._writer.send(
            ProgressFrame(done=done, total=total, message=message).model_dump()
        )

    def get_context_record(self) -> dict[str, Any]:
        """Return the record that triggered this workflow step.

        `Ctx` has no ambient `.record`/`.dataset` fields the way in-process
        WorkflowContext does -- this (and get_context_dataset()) is the
        only way an out-of-process plugin learns what triggered it.
        """
        result = self._call_tool("get_context_record", {})
        return result["record"]

    def get_context_dataset(self) -> dict[str, Any]:
        """Return the dataset that owns `get_context_record()`'s record."""
        result = self._call_tool("get_context_dataset", {})
        return result["dataset"]

    def get_file(self, sha256: str) -> bytes:
        """Return the raw bytes stored under `sha256` in the object store."""
        result = self._call("get_file", {"sha256": sha256})
        return decode_binary(result)

    def file_path(self, sha256: str) -> Path:
        """Return a path to a read-only copy of a stored file, in the run's folder.

        Prefer this to `get_file` for anything large: nothing is read into
        memory or sent over the protocol. The copy is removed when the run
        ends. Needs `read` (protocol 3).
        """
        result = self._call_tool("file_path", {"sha256": sha256})
        return Path(result["path"])

    def store_path(self, path: str | Path, filename: str) -> dict[str, Any]:
        """Store the file at `path` (which must be in the run's folder: `run_dir`) and return its `FileRef` dict.

        Prefer this to `store_file` for anything large: the host reads the
        file itself. Needs `manage_files` (protocol 3).
        """
        result = self._call_tool(
            "store_path", {"path": str(Path(path).resolve()), "filename": filename}
        )
        return result["file"]

    @property
    def run_dir(self) -> Path | None:
        """The run's folder, where a plugin may write files to `store_path` (None from an older host)."""
        return self._scratch_dir

    def store_file(self, data: bytes, filename: str) -> dict[str, Any]:
        """Write `data` to the object store and return its `FileRef` dict (`{sha256, filename, size}`)."""
        result = self._call_tool(
            "store_file",
            {"data": encode_binary(data, self._scratch_dir), "filename": filename},
        )
        return result["file"]

    def update_record(self, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Replace the values of the record identified by `record_id` with `data` and return it.

        Fields not in `data` are cleared; to change only some fields use
        `patch_record`. Needs `write_records`.
        """
        return self._call("update_record", {"record_id": record_id, "data": data})

    def create_record(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        context_record_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a record in `dataset_name` against `schema_name` and return it.

        `context_record_id`, when omitted, defaults host-side to
        get_context_record()'s id -- see WorkflowContext.create_record's
        docstring for why it isn't called parent_record_id.
        """
        return self._call(
            "create_record",
            {
                "dataset_name": dataset_name,
                "schema_name": schema_name,
                "data": data,
                "context_record_id": context_record_id,
            },
        )

    def patch_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Change only `fields` of a record and return it; every other field stays as it is now.

        Prefer this to `update_record`, which replaces the record's whole
        data with what it is given (so fields left out are cleared). Nothing
        is written, and nothing is triggered, when the fields already hold
        these values. Needs `write_records`.
        """
        result = self._call_tool(
            "patch_record", {"record_id": record_id, "fields": fields}
        )
        return result["record"]

    def get_record(self, record_id: str) -> dict[str, Any]:
        """Return the record identified by `record_id`."""
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
        """Return records in `dataset_name` matching the given filters.

        Args:
            dataset_name: Dataset to search within.
            schema_name: Restrict to records of this schema, if given.
            parent_record_id: Restrict to children of this record, if given.
            filters: Host-parsed filter expressions (field/operator/value),
                ANDed together.
            search: Free-text search over the dataset's searchable fields.
            limit: Maximum number of records to return.
            offset: Number of matching records to skip, for pagination.

        Returns:
            The matching records, most-recent-first.
        """
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
        """Delete the record identified by `record_id`."""
        self._call_tool("delete_record", {"record_id": record_id})

    def get_schema(self, name: str) -> dict[str, Any]:
        """Return the schema named `name`, including its resolved fields."""
        result = self._call_tool("get_schema", {"name": name})
        return result["schema"]

    def list_schemas(self) -> list[dict[str, Any]]:
        """Return every schema in the project."""
        result = self._call_tool("list_schemas", {})
        return result["schemas"]

    def get_collection(self, name: str) -> dict[str, Any]:
        """Return the collection named `name`."""
        result = self._call_tool("get_collection", {"name": name})
        return result["collection"]

    def list_collections(self) -> list[dict[str, Any]]:
        """Return every collection in the project."""
        result = self._call_tool("list_collections", {})
        return result["collections"]

    def commit(self) -> None:
        """Do nothing (deprecated).

        A run's writes are kept or dropped whole when it ends: civex keeps
        them if every step succeeds and undoes them all if one fails, so a
        plugin no longer commits part of a run. Kept so plugins that call it
        still run; it sends nothing.
        """
        warnings.warn(
            "Ctx.commit() does nothing: civex keeps a run's writes when the run "
            "ends, or none of them if it fails.",
            DeprecationWarning,
            stacklevel=2,
        )
