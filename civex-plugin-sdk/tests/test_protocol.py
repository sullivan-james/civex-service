from pathlib import Path

import pytest

from civex_plugin_sdk.protocol import (
    BINARY_INLINE_THRESHOLD,
    DescribeResult,
    RpcCall,
    decode_binary,
    encode_binary,
    parse_frame,
)


def test_parse_frame_roundtrips_known_types():
    raw = {
        "type": "describe_result",
        "id": "example.echo",
        "name": "Echo",
        "category": "example",
        "capabilities": ["commit"],
        "config_schema": {"type": "object"},
    }
    frame = parse_frame(raw)
    assert isinstance(frame, DescribeResult)
    assert frame.id == "example.echo"
    assert frame.capabilities == ["commit"]


def test_parse_frame_rejects_unknown_type():
    with pytest.raises(ValueError):
        parse_frame({"type": "not_a_real_frame"})


def test_rpc_call_defaults_params_to_empty_dict():
    call = RpcCall(call_id="abc", method="commit")
    assert call.params == {}


def test_encode_binary_inlines_small_payload():
    payload = encode_binary(b"hello world")
    assert payload == {"encoding": "base64", "data": "aGVsbG8gd29ybGQ="}
    assert decode_binary(payload) == b"hello world"


def test_encode_binary_spills_to_scratch_above_threshold(tmp_path: Path):
    data = b"x" * (BINARY_INLINE_THRESHOLD + 1)
    payload = encode_binary(data, scratch_dir=tmp_path)
    assert payload["encoding"] == "path"
    assert Path(payload["path"]).read_bytes() == data
    assert decode_binary(payload) == data


def test_encode_binary_inlines_when_no_scratch_dir_even_above_threshold():
    data = b"x" * (BINARY_INLINE_THRESHOLD + 1)
    payload = encode_binary(data, scratch_dir=None)
    assert payload["encoding"] == "base64"
    assert decode_binary(payload) == data


def test_decode_binary_rejects_unknown_encoding():
    with pytest.raises(ValueError):
        decode_binary({"encoding": "smoke_signal"})
