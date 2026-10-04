"""`civex.parse_table`: reading CSV, TSV and other delimited text, one separator or
several the file may use."""

from __future__ import annotations

import pytest
from civex_plugin_sdk.io_convert import to_invoke_form
from pydantic import ValidationError as PydanticValidationError

from civex.domain.exceptions import ValidationError
from civex.plugins.builtins.parse_table import (
    Plugin,
    detect_delimiter,
    resolve_delimiter,
)
from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin

Config = Plugin.Config


@pytest.fixture()
def wf_ctx(ctx, make_collection, make_schema, make_record) -> WorkflowContext:
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    record = make_record("study", "trigger", {})
    return WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)


def _read(wf_ctx, raw: bytes, **config):
    registration = get_plugin("civex.parse_table")
    result = registration.invoke(
        {"bytes": raw}, registration.config_model(**config), wf_ctx, 60.0
    )
    return to_invoke_form("table", result.outputs["table"])


CSV = b"name,age\nAlice,30\nBob,25\n"
TSV = b"name\tage\nAlice\t30\nBob\t25\n"


def test_one_workflow_reads_both_csv_and_tsv(wf_ctx) -> None:
    for raw in (CSV, TSV):
        df = _read(wf_ctx, raw, delimiters=[",", "tab"])
        assert list(df.columns) == ["name", "age"]
        assert df["age"].tolist() == [30, 25]


def test_the_order_listed_does_not_matter_when_the_file_is_clear(wf_ctx) -> None:
    df = _read(wf_ctx, TSV, delimiters=["tab", ","])
    assert list(df.columns) == ["name", "age"]
    df = _read(wf_ctx, CSV, delimiters=["tab", ","])
    assert list(df.columns) == ["name", "age"]


def test_a_third_separator_can_be_allowed_too(wf_ctx) -> None:
    semi = b"name;age\nAlice;30\n"
    assert list(_read(wf_ctx, semi, delimiters=[",", "tab", ";"]).columns) == [
        "name",
        "age",
    ]


def test_commas_inside_quotes_do_not_fool_the_choice(wf_ctx) -> None:
    # A tab-separated file whose text fields are full of commas.
    raw = b'note\tcount\n"a, b, c, d"\t1\n"e, f, g"\t2\n'
    df = _read(wf_ctx, raw, delimiters=[",", "tab"])
    assert list(df.columns) == ["note", "count"]
    assert df["note"].tolist() == ["a, b, c, d", "e, f, g"]


def test_a_file_that_mentions_the_other_separator_in_a_field(wf_ctx) -> None:
    # CSV with one stray tab in a value: the commas are what is steady.
    raw = b"name,note\nAlice,a\tb\nBob,c\n"
    df = _read(wf_ctx, raw, delimiters=["tab", ","])
    assert list(df.columns) == ["name", "note"]


def test_a_single_column_file_uses_the_first_separator_listed(wf_ctx) -> None:
    df = _read(wf_ctx, b"name\nAlice\nBob\n", delimiters=[",", "tab"])
    assert list(df.columns) == ["name"]
    assert df["name"].tolist() == ["Alice", "Bob"]


def test_windows_line_endings_and_a_byte_order_mark(wf_ctx) -> None:
    raw = b"\xef\xbb\xbfname\tage\r\nAlice\t30\r\n"
    df = _read(wf_ctx, raw, delimiters=[",", "tab"])
    assert list(df.columns) == ["name", "age"]  # no BOM stuck to "name"
    assert df["age"].tolist() == [30]


def test_a_byte_order_mark_is_dropped_with_a_single_separator_too(wf_ctx) -> None:
    df = _read(wf_ctx, b"\xef\xbb\xbfname,age\nAlice,30\n")
    assert list(df.columns) == ["name", "age"]


def test_the_single_delimiter_setting_still_works_and_accepts_a_name(wf_ctx) -> None:
    assert list(_read(wf_ctx, CSV).columns) == ["name", "age"]  # the default, a comma
    assert list(_read(wf_ctx, TSV, delimiter="tab").columns) == ["name", "age"]
    assert list(_read(wf_ctx, TSV, delimiter="\t").columns) == ["name", "age"]
    assert list(_read(wf_ctx, TSV, delimiter="\\t").columns) == ["name", "age"]


def test_a_regular_expression_delimiter_is_still_passed_to_pandas(wf_ctx) -> None:
    # `delimiter` has always been handed straight to pandas, which reads a
    # multi-character one as a regular expression; a workflow may rely on that.
    df = _read(wf_ctx, b"a   b\n1   2\n", delimiter=r"\s+")
    assert list(df.columns) == ["a", "b"]
    assert df["b"].tolist() == [2]


def test_delimiters_overrides_delimiter(wf_ctx) -> None:
    df = _read(wf_ctx, TSV, delimiter=",", delimiters=[",", "tab"])
    assert list(df.columns) == ["name", "age"]


def test_a_separator_in_the_list_must_be_one_character() -> None:
    with pytest.raises(PydanticValidationError, match="single separator"):
        Config(delimiters=[",", "||"])
    with pytest.raises(PydanticValidationError, match="at least one"):
        Config(delimiters=[])


def test_empty_and_undecodable_input_are_reported_plainly(wf_ctx) -> None:
    with pytest.raises(ValidationError, match="no data"):
        _read(wf_ctx, b"", delimiters=[",", "tab"])
    with pytest.raises(ValidationError, match="decode"):
        _read(wf_ctx, b"\xff\xfe\x00bad", delimiters=[",", "tab"], encoding="ascii")


def test_resolving_names_and_characters() -> None:
    assert resolve_delimiter("TAB") == "\t"
    assert resolve_delimiter("Comma") == ","
    assert resolve_delimiter("|") == "|"
    assert resolve_delimiter("\\t") == "\t"
    with pytest.raises(ValueError):
        resolve_delimiter("ab")


def test_detecting_prefers_the_steadiest_then_the_most_then_the_first() -> None:
    assert detect_delimiter("a,b\n1,2\n", [",", "\t"]) == ","
    assert detect_delimiter("a\tb\n1\t2\n", [",", "\t"]) == "\t"
    # Both appear equally on every line: the first listed wins.
    assert detect_delimiter("a,b\tc\n1,2\t3\n", ["\t", ","]) == "\t"
    # Only one is steady across lines.
    assert detect_delimiter("a,b\tc\n1,2,3\n", ["\t", ","]) == ","
    assert detect_delimiter("", [",", "\t"]) == ","
