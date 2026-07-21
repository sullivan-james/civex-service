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


def test_update_record_sends_data_and_expects_no_return():
    ctx, sent = make_ctx(
        lambda call: {"type": "rpc_result", "call_id": call["call_id"], "result": {}}
    )
    assert ctx.update_record({"field": "value"}) is None
    assert sent[-1]["method"] == "update_record"
    assert sent[-1]["params"] == {"data": {"field": "value"}}


def test_create_record_returns_host_result():
    ctx, sent = make_ctx(
        lambda call: {
            "type": "rpc_result",
            "call_id": call["call_id"],
            "result": {"id": "new-record-id"},
        }
    )
    result = ctx.create_record("ds", "schema", {"a": 1}, parent_record_id="parent-1")
    assert result == {"id": "new-record-id"}
    assert sent[-1]["params"] == {
        "dataset_name": "ds",
        "schema_name": "schema",
        "data": {"a": 1},
        "parent_record_id": "parent-1",
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
            "error": {"code": "capability_denied", "message": "nope"},
        }
    )
    with pytest.raises(RpcError) as exc_info:
        ctx.commit()
    assert exc_info.value.code == "capability_denied"
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
