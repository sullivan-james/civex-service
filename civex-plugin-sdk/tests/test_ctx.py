import json
from collections.abc import Callable
from typing import Any

import pytest

from civex_plugin_sdk.ctx import Ctx
from civex_plugin_sdk.errors import RpcError
from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.protocol import encode_binary


def make_ctx(responder: Callable[[dict[str, Any]], dict[str, Any]]) -> tuple[Ctx, list]:
    """Wires a Ctx to a fake host: `responder` is called with the most
    recently-sent rpc_call frame and returns the frame the "host" replies
    with. Sidesteps needing to predict Ctx's random call_id up front."""
    sent: list[dict[str, Any]] = []
    writer = FrameWriter(lambda line: sent.append(json.loads(line)))

    def response_lines():
        while True:
            yield json.dumps(responder(sent[-1]))

    reader = FrameReader(response_lines())
    return Ctx(writer, reader), sent


def test_get_file_decodes_base64_result():
    ctx, sent = make_ctx(
        lambda call: {
            "type": "rpc_result",
            "call_id": call["call_id"],
            "result": encode_binary(b"file bytes"),
        }
    )
    result = ctx.get_file("deadbeef")
    assert result == b"file bytes"
    assert sent[-1] == {
        "type": "rpc_call",
        "call_id": sent[-1]["call_id"],
        "method": "get_file",
        "params": {"sha256": "deadbeef"},
    }


def test_update_record_sends_explicit_record_id_and_data():
    ctx, sent = make_ctx(
        lambda call: {
            "type": "rpc_result",
            "call_id": call["call_id"],
            "result": {"id": "r1", "data": {"field": "value"}},
        }
    )
    result = ctx.update_record("r1", {"field": "value"})
    assert result == {"id": "r1", "data": {"field": "value"}}
    assert sent[-1]["method"] == "update_record"
    assert sent[-1]["params"] == {"record_id": "r1", "data": {"field": "value"}}


def test_create_record_returns_host_result():
    ctx, sent = make_ctx(
        lambda call: {
            "type": "rpc_result",
            "call_id": call["call_id"],
            "result": {"id": "new-record-id"},
        }
    )
    result = ctx.create_record("ds", "schema", {"a": 1}, context_record_id="ctx-1")
    assert result == {"id": "new-record-id"}
    assert sent[-1]["params"] == {
        "dataset_name": "ds",
        "schema_name": "schema",
        "data": {"a": 1},
        "context_record_id": "ctx-1",
    }


def test_commit_sends_empty_params():
    ctx, sent = make_ctx(
        lambda call: {"type": "rpc_result", "call_id": call["call_id"], "result": {}}
    )
    ctx.commit()
    assert sent[-1] == {
        "type": "rpc_call",
        "call_id": sent[-1]["call_id"],
        "method": "commit",
        "params": {},
    }


def test_error_response_raises_rpc_error_with_host_code_and_message():
    ctx, _ = make_ctx(
        lambda call: {
            "type": "error",
            "call_id": call["call_id"],
            "error": {"kind": "capability_denied", "message": "nope"},
        }
    )
    with pytest.raises(RpcError) as exc_info:
        ctx.commit()
    assert exc_info.value.kind == "capability_denied"
    assert exc_info.value.message == "nope"


def test_mismatched_call_id_raises_rpc_error():
    ctx, _ = make_ctx(
        lambda call: {
            "type": "rpc_result",
            "call_id": "some-other-call-id",
            "result": {},
        }
    )
    with pytest.raises(RpcError):
        ctx.commit()


def _tool_result(result: dict[str, Any]):
    return lambda call: {
        "type": "rpc_result",
        "call_id": call["call_id"],
        "result": result,
    }


def test_get_record_routes_through_call_tool():
    ctx, sent = make_ctx(_tool_result({"record": {"id": "r1", "data": {"a": 1}}}))

    result = ctx.get_record("r1")

    assert result == {"id": "r1", "data": {"a": 1}}
    assert sent[-1]["method"] == "call_tool"
    assert sent[-1]["params"] == {"tool": "get_record", "args": {"record_id": "r1"}}


def test_find_records_routes_through_call_tool_and_returns_list():
    ctx, sent = make_ctx(_tool_result({"records": [{"id": "r1"}, {"id": "r2"}]}))

    result = ctx.find_records("study", schema_name="subject", filters=["status=active"])

    assert result == [{"id": "r1"}, {"id": "r2"}]
    assert sent[-1]["params"] == {
        "tool": "find_records",
        "args": {
            "dataset_name": "study",
            "schema_name": "subject",
            "parent_record_id": None,
            "filters": ["status=active"],
            "search": None,
            "limit": 50,
            "offset": 0,
        },
    }


def test_delete_record_routes_through_call_tool():
    ctx, sent = make_ctx(_tool_result({}))

    assert ctx.delete_record("r1") is None
    assert sent[-1]["params"] == {"tool": "delete_record", "args": {"record_id": "r1"}}


def test_get_context_record_routes_through_call_tool_with_no_args():
    ctx, sent = make_ctx(_tool_result({"record": {"id": "trigger-1", "data": {}}}))

    result = ctx.get_context_record()

    assert result == {"id": "trigger-1", "data": {}}
    assert sent[-1]["params"] == {"tool": "get_context_record", "args": {}}


def test_get_context_dataset_routes_through_call_tool_with_no_args():
    ctx, sent = make_ctx(_tool_result({"dataset": {"name": "study"}}))

    result = ctx.get_context_dataset()

    assert result == {"name": "study"}
    assert sent[-1]["params"] == {"tool": "get_context_dataset", "args": {}}


def test_store_file_encodes_outbound_bytes_and_returns_file_ref():
    ctx, sent = make_ctx(
        _tool_result(
            {"file": {"sha256": "abc123", "filename": "hello.txt", "size": 11}}
        )
    )

    result = ctx.store_file(b"hello world", "hello.txt")

    assert result == {"sha256": "abc123", "filename": "hello.txt", "size": 11}
    call_args = sent[-1]["params"]["args"]
    assert call_args["filename"] == "hello.txt"
    assert call_args["data"] == encode_binary(b"hello world")


def test_get_schema_routes_through_call_tool():
    ctx, sent = make_ctx(
        _tool_result({"schema": {"name": "subject", "fields": [{"name": "age"}]}})
    )

    result = ctx.get_schema("subject")

    assert result == {"name": "subject", "fields": [{"name": "age"}]}
    assert sent[-1]["params"] == {"tool": "get_schema", "args": {"name": "subject"}}


def test_list_schemas_routes_through_call_tool_and_returns_list():
    ctx, sent = make_ctx(_tool_result({"schemas": [{"name": "subject"}]}))

    result = ctx.list_schemas()

    assert result == [{"name": "subject"}]
    assert sent[-1]["params"] == {"tool": "list_schemas", "args": {}}


def test_get_collection_routes_through_call_tool():
    ctx, sent = make_ctx(_tool_result({"collection": {"name": "study"}}))

    result = ctx.get_collection("study")

    assert result == {"name": "study"}
    assert sent[-1]["params"] == {"tool": "get_collection", "args": {"name": "study"}}


def test_list_collections_routes_through_call_tool_and_returns_list():
    ctx, sent = make_ctx(_tool_result({"collections": [{"name": "study"}]}))

    result = ctx.list_collections()

    assert result == [{"name": "study"}]
    assert sent[-1]["params"] == {"tool": "list_collections", "args": {}}
