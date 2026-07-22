import json
from typing import Any

from pydantic import BaseModel

from civex_plugin_sdk.ctx import Ctx
from civex_plugin_sdk.errors import CapabilityDeniedError
from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.plugin import Plugin
from civex_plugin_sdk.plugin_base import IOSpec
from civex_plugin_sdk.serve import serve_loop


class GreetPlugin(Plugin):
    id = "test.greet"
    name = "Greet"
    description = "Echoes its config text back."
    category = "test"
    capabilities = ["commit"]
    inputs = [IOSpec(name="call_commit", type="boolean", required=False)]
    outputs = [
        IOSpec(name="echo", type="string"),
        IOSpec(name="inputs", type="mapping"),
    ]

    class Config(BaseModel):
        text: str

    def invoke(self, inputs: dict[str, Any], config: Config, ctx: Ctx) -> dict:
        if inputs.get("call_commit"):
            ctx.commit()
        return {"echo": config.text, "inputs": inputs}


class BoomPlugin(Plugin):
    id = "test.boom"
    name = "Boom"

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx):
        raise ValueError("kaboom")


class DeniedPlugin(Plugin):
    id = "test.denied"
    name = "Denied"

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx):
        raise CapabilityDeniedError("get_file")


def _run(plugin_cls, lines):
    sent: list[dict] = []
    writer = FrameWriter(lambda line: sent.append(json.loads(line)))
    reader = FrameReader(lines)
    serve_loop(plugin_cls, reader, writer)
    return sent


def test_describe_reports_the_plugins_whole_declared_contract():
    sent = _run(GreetPlugin, [json.dumps({"type": "describe"})])
    assert sent == [
        {
            "type": "describe_result",
            "id": "test.greet",
            "name": "Greet",
            "description": "Echoes its config text back.",
            "category": "test",
            "capabilities": ["commit"],
            "inputs": [
                {
                    "name": "call_commit",
                    "type": "boolean",
                    "required": False,
                    "description": "",
                }
            ],
            "outputs": [
                {
                    "name": "echo",
                    "type": "string",
                    "required": True,
                    "description": "",
                },
                {
                    "name": "inputs",
                    "type": "mapping",
                    "required": True,
                    "description": "",
                },
            ],
            "config_schema": GreetPlugin.Config.model_json_schema(),
        }
    ]


def test_describe_reports_an_undeclared_contract_as_null_not_empty():
    """A plugin written against an older SDK (or one that simply declares
    nothing beyond id/name) must still describe successfully rather than
    failing discovery -- and its silence must stay distinguishable from an
    explicit "I take no inputs", since the host enforces the latter."""
    sent = _run(BoomPlugin, [json.dumps({"type": "describe"})])
    assert sent[0]["description"] == ""
    assert sent[0]["inputs"] is None
    assert sent[0]["outputs"] is None


def test_run_success_returns_result_frame():
    sent = _run(
        GreetPlugin,
        [json.dumps({"type": "run", "inputs": {}, "config": {"text": "hi"}})],
    )
    assert sent == [{"type": "result", "outputs": {"echo": "hi", "inputs": {}}}]


def test_run_with_invalid_config_returns_config_validation_error():
    sent = _run(
        GreetPlugin,
        [json.dumps({"type": "run", "inputs": {}, "config": {}})],  # missing "text"
    )
    assert len(sent) == 1
    assert sent[0]["type"] == "error"
    assert sent[0]["error"]["kind"] == "config_validation_error"


def test_run_where_invoke_raises_plain_exception_wraps_as_plugin_error():
    sent = _run(BoomPlugin, [json.dumps({"type": "run", "inputs": {}, "config": {}})])
    assert sent == [
        {
            "type": "error",
            "call_id": None,
            "error": {"kind": "plugin_error", "message": "kaboom", "retryable": False},
        }
    ]


def test_run_where_invoke_raises_typed_plugin_error_preserves_code():
    sent = _run(DeniedPlugin, [json.dumps({"type": "run", "inputs": {}, "config": {}})])
    assert sent[0]["error"]["kind"] == "capability_denied"


def test_unexpected_frame_type_on_control_channel_yields_protocol_error():
    sent = _run(
        GreetPlugin,
        [json.dumps({"type": "rpc_result", "call_id": "x", "result": {}})],
    )
    assert sent[0]["type"] == "error"
    assert sent[0]["error"]["kind"] == "protocol_error"


def test_run_with_nested_rpc_call_is_answered_mid_dispatch():
    """The reader is asked for a second frame *during* invoke() (from
    inside ctx.commit()), before serve_loop's own top-level iteration
    resumes -- this is the interleaving the wire protocol depends on."""
    sent: list[dict] = []
    writer = FrameWriter(lambda line: sent.append(json.loads(line)))

    def lines():
        yield json.dumps(
            {"type": "run", "inputs": {"call_commit": True}, "config": {"text": "hi"}}
        )
        call = sent[-1]
        assert call == {
            "type": "rpc_call",
            "call_id": call["call_id"],
            "method": "commit",
            "params": {},
        }
        yield json.dumps(
            {"type": "rpc_result", "call_id": call["call_id"], "result": {}}
        )

    reader = FrameReader(lines())
    serve_loop(GreetPlugin, reader, writer)

    assert sent[-1] == {
        "type": "result",
        "outputs": {"echo": "hi", "inputs": {"call_commit": True}},
    }
