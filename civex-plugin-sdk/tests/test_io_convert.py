import base64
import json
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.io_convert import (
    convert_inputs,
    convert_outputs,
    to_invoke_form,
    to_wire_form,
)
from civex_plugin_sdk.plugin import Plugin
from civex_plugin_sdk.plugin_base import IOSpec
from civex_plugin_sdk.serve import serve_loop


def test_to_invoke_form_converts_table_records_to_a_dataframe():
    df = to_invoke_form("table", [{"a": 1}, {"a": 2}])
    assert isinstance(df, pd.DataFrame)
    assert df.to_dict(orient="records") == [{"a": 1}, {"a": 2}]


def test_to_invoke_form_leaves_an_already_converted_dataframe_alone():
    df = pd.DataFrame([{"a": 1}])
    assert to_invoke_form("table", df) is df


def test_to_invoke_form_decodes_base64_bytes():
    encoded = base64.b64encode(b"hello").decode("ascii")
    assert to_invoke_form("bytes", encoded) == b"hello"


def test_to_invoke_form_leaves_already_raw_bytes_alone():
    assert to_invoke_form("bytes", b"hello") == b"hello"


def test_to_invoke_form_passes_through_unrelated_types_unchanged():
    assert to_invoke_form("string", "hi") == "hi"
    assert to_invoke_form("table", "not a list") == "not a list"


def test_to_wire_form_converts_a_dataframe_to_an_inline_columnar_envelope():
    df = pd.DataFrame([{"a": 1}, {"a": 2}])
    assert to_wire_form("table", df) == {
        "encoding": "inline",
        "columns": ["a"],
        "dtypes": {"a": "integer"},
        "data": {"a": [1, 2]},
    }


def test_to_wire_form_converts_a_plain_records_list_to_the_same_envelope():
    """Even without a DataFrame -- e.g. a non-pandas author's own
    hand-built list of rows -- the wire form gets the same columnar/typed
    treatment, not just DataFrames."""
    records = [{"a": 1}]
    assert to_wire_form("table", records) == {
        "encoding": "inline",
        "columns": ["a"],
        "dtypes": {"a": "integer"},
        "data": {"a": [1]},
    }


def test_to_wire_form_leaves_an_already_built_envelope_alone():
    """An author (or another tier's SDK) that already produced the envelope
    shape directly isn't double-converted."""
    envelope = {
        "encoding": "inline",
        "columns": ["a"],
        "dtypes": {"a": "integer"},
        "data": {"a": [1]},
    }
    assert to_wire_form("table", envelope) is envelope


def test_to_wire_form_infers_civex_dtypes_not_pandas_ones():
    df = pd.DataFrame(
        {
            "n": pd.array([1, 2], dtype="int64"),
            "x": pd.array([1.5, 2.5], dtype="float64"),
            "ok": pd.array([True, False], dtype="bool"),
            "label": ["a", "b"],
        }
    )
    wire = to_wire_form("table", df)
    assert wire["dtypes"] == {
        "n": "integer",
        "x": "float",
        "ok": "boolean",
        "label": "string",
    }


def test_to_wire_form_round_trips_datetime_columns_with_real_type_fidelity():
    """The old plain-records shape lost this entirely -- a datetime column
    became bare strings with no way to tell it apart from a string column."""
    df = pd.DataFrame({"seen_at": pd.to_datetime(["2024-01-02T03:04:05Z"])})
    wire = to_wire_form("table", df)
    assert wire["dtypes"]["seen_at"] == "datetime"

    back = to_invoke_form("table", wire)
    assert pd.api.types.is_datetime64_any_dtype(back["seen_at"])
    assert back["seen_at"].iloc[0].isoformat().startswith("2024-01-02")


def test_to_wire_form_writes_a_large_table_to_an_ndjson_scratch_file(tmp_path):
    rows = [{"a": i} for i in range(11_000)]
    wire = to_wire_form("table", rows, scratch_dir=tmp_path)
    assert wire["encoding"] == "ndjson_path"
    path = tmp_path / wire["path"].rsplit("/", 1)[-1]
    lines = path.read_text().splitlines()
    assert json.loads(lines[0]) == {"columns": ["a"], "dtypes": {"a": "integer"}}
    assert len(lines) == 1 + 11_000
    assert json.loads(lines[1]) == {"a": 0}


def test_scratch_paths_are_always_absolute_even_from_a_relative_scratch_dir(
    tmp_path, monkeypatch
):
    """Regression: serve.py's _handle_run passes Path(".") as scratch_dir
    (a Tier 1 plugin's cwd is already the host-managed scratch dir) -- a
    bare relative path built from that (e.g. Path(".") / "x.ndjson") is only
    meaningful relative to *this* process. Embedding it as-is in the wire
    envelope silently resolves to the wrong file once the host (a different
    cwd) or a later step reads it back."""
    monkeypatch.chdir(tmp_path)

    big_rows = [{"a": i} for i in range(11_000)]
    table_wire = to_wire_form("table", big_rows, scratch_dir=Path("."))
    assert Path(table_wire["path"]).is_absolute()
    assert Path(table_wire["path"]).exists()

    from civex_plugin_sdk.protocol import BINARY_INLINE_THRESHOLD

    bytes_wire = to_wire_form(
        "bytes", b"x" * (BINARY_INLINE_THRESHOLD + 1), scratch_dir=Path(".")
    )
    assert Path(bytes_wire["path"]).is_absolute()
    assert Path(bytes_wire["path"]).exists()


def test_to_wire_form_stays_inline_below_the_row_threshold_even_with_scratch_dir(
    tmp_path,
):
    rows = [{"a": 1}]
    assert to_wire_form("table", rows, scratch_dir=tmp_path)["encoding"] == "inline"


def test_to_invoke_form_reconstructs_a_dataframe_from_an_ndjson_scratch_file(
    tmp_path,
):
    rows = [{"a": i} for i in range(11_000)]
    wire = to_wire_form("table", rows, scratch_dir=tmp_path)
    back = to_invoke_form("table", wire)
    assert isinstance(back, pd.DataFrame)
    assert len(back) == 11_000
    assert back["a"].iloc[-1] == 10_999


def test_to_wire_form_encodes_raw_bytes_via_the_shared_binary_envelope():
    """Same {"encoding": ..., ...} shape civex_plugin_sdk.protocol's
    encode_binary/get_file already use, so a bytes-typed IOSpec output gets
    the identical inline-vs-scratch-file size handling."""
    assert to_wire_form("bytes", b"hello") == {
        "encoding": "base64",
        "data": base64.b64encode(b"hello").decode("ascii"),
    }


def test_to_wire_form_writes_large_bytes_to_scratch_when_a_scratch_dir_is_given(
    tmp_path,
):
    from civex_plugin_sdk.protocol import BINARY_INLINE_THRESHOLD

    big = b"x" * (BINARY_INLINE_THRESHOLD + 1)
    wire = to_wire_form("bytes", big, scratch_dir=tmp_path)
    assert wire["encoding"] == "path"
    assert Path(wire["path"]).read_bytes() == big


def test_to_invoke_form_decodes_the_new_binary_envelope():
    encoded = to_wire_form("bytes", b"hello")
    assert to_invoke_form("bytes", encoded) == b"hello"


def test_convert_inputs_and_outputs_apply_only_to_declared_names():
    specs = [IOSpec(name="table", type="table"), IOSpec(name="label", type="string")]
    converted = convert_inputs(specs, {"table": [{"a": 1}], "label": "x", "extra": 1})
    assert isinstance(converted["table"], pd.DataFrame)
    assert converted["label"] == "x"
    assert converted["extra"] == 1  # no declared spec -- passed through untouched


def test_convert_inputs_and_outputs_are_a_noop_with_no_declared_specs():
    values = {"table": [{"a": 1}]}
    assert convert_inputs(None, values) is values
    assert convert_outputs([], values) is values


class TablePlugin(Plugin):
    id = "test.table"
    name = "Table"
    category = "test"
    inputs = [IOSpec(name="table", type="table")]
    outputs = [IOSpec(name="table", type="table"), IOSpec(name="rows", type="number")]

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx):
        df = inputs["table"]
        assert isinstance(df, pd.DataFrame), "author code should see a real DataFrame"
        return {"table": df, "rows": len(df)}


def _run(plugin_cls, lines):
    sent: list[dict] = []
    writer = FrameWriter(lambda line: sent.append(json.loads(line)))
    reader = FrameReader(lines)
    serve_loop(plugin_cls, reader, writer)
    return sent


def test_serve_converts_table_records_to_a_dataframe_and_back_across_the_wire():
    sent = _run(
        TablePlugin,
        [
            json.dumps(
                {
                    "type": "run",
                    "inputs": {"table": [{"a": 1}, {"a": 2}]},
                    "config": {},
                }
            )
        ],
    )
    assert sent == [
        {
            "type": "result",
            "outputs": {
                "table": {
                    "encoding": "inline",
                    "columns": ["a"],
                    "dtypes": {"a": "integer"},
                    "data": {"a": [1, 2]},
                },
                "rows": 2,
            },
        }
    ]


def test_to_invoke_form_degrades_to_plain_records_when_pandas_unavailable(monkeypatch):
    """An author who declares `type="table"` without installing the
    `[table]` extra still gets *something* usable (plain records) rather
    than a crash."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("no pandas here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    records = [{"a": 1}]
    assert to_invoke_form("table", records) is records
