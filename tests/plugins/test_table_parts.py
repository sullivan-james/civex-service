"""`civex.table@1` read a part at a time and exactly as written: what the import
wizard asks of it for a large file."""

from __future__ import annotations

import io

import pytest
from civex_plugin_sdk.io_convert import to_invoke_form

from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin


@pytest.fixture()
def wf_ctx(ctx) -> WorkflowContext:
    return WorkflowContext(record=None, dataset=None, _app_ctx=ctx)


def _read(wf_ctx, raw: bytes, name: str, **config):
    ref = wf_ctx._app_ctx.file_svc.store_bytes(raw, name)
    step = get_plugin("civex.table@1")
    result = step.invoke(
        {"files": [ref.to_dict()]}, step.config_model(**config), wf_ctx, 60.0
    )
    return to_invoke_form("table", result.outputs["table"])


CSV = b"id,n,note\n007,1,a\n008,,b\n009,3,\n010,4,d\n"


def _xlsx() -> bytes:
    import openpyxl

    book = openpyxl.Workbook()
    for row in (["id", "n"], ["007", 1], ["008", None], ["009", 3]):
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_a_part_of_the_rows_is_read(wf_ctx, kind) -> None:
    raw, name = (CSV, "t.csv") if kind == "csv" else (_xlsx(), "t.xlsx")
    df = _read(wf_ctx, raw, name, as_text=True, skip_rows=1, max_rows=2)
    assert df["id"].tolist() == ["008", "009"]


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_values_are_kept_as_written(wf_ctx, kind) -> None:
    raw, name = (CSV, "t.csv") if kind == "csv" else (_xlsx(), "t.xlsx")
    df = _read(wf_ctx, raw, name, as_text=True)
    assert df["id"].tolist()[0] == "007"  # not 7
    assert df["n"].tolist()[1] == ""  # blank, not NaN or 8.0


def test_only_the_named_columns_are_read(wf_ctx) -> None:
    df = _read(wf_ctx, CSV, "t.csv", as_text=True, only_columns=["id", "note"])
    assert list(df.columns) == ["id", "note"]


def test_without_as_written_numbers_are_still_worked_out(wf_ctx) -> None:
    df = _read(wf_ctx, CSV, "t.csv")
    assert df["id"].tolist()[0] == 7


BLANKS = b"id,v\na,1\n\nb,2\nc,3\n\nd,4\ne,5\nf,6\n"


def test_parts_of_a_text_file_with_blank_lines_hold_every_row_once(wf_ctx) -> None:
    """Skipping counts rows of data, not lines: a blank line before a part
    boundary must not move the boundary."""
    seen: list[str] = []
    for start in range(0, 8, 2):
        df = _read(wf_ctx, BLANKS, "t.csv", as_text=True, skip_rows=start, max_rows=2)
        seen += df["id"].tolist()
    assert seen == ["a", "b", "c", "d", "e", "f"]
    assert _read(wf_ctx, BLANKS, "t.csv", as_text=True, skip_rows=6).empty


def test_parts_of_an_excel_sheet_with_a_blank_row_hold_every_row_once(wf_ctx) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    for row in (["id", "v"], ["a", 1], [None, None], ["b", 2], ["c", 3], ["d", 4]):
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    seen: list[str] = []
    for start in range(0, 6, 2):
        df = _read(
            wf_ctx, out.getvalue(), "t.xlsx", as_text=True, skip_rows=start, max_rows=2
        )
        seen += [i for i in df["id"].tolist() if i != ""]
    assert seen == ["a", "b", "c", "d"]
