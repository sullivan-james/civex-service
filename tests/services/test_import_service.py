"""Bringing a spreadsheet in: `ImportService` reads it with the Table step and
saves it with the Save-as-records step, a part at a time.

What these hold: what a column looks like (and what it must not be taken for),
the fields made from headings, update/skip/add by a key, rows that can't be
saved named plainly, a check that gives what the save will give and keeps
nothing, a file brought in in parts the same as whole, and a large file."""

from __future__ import annotations

import io
import time

import pytest

from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.table_import import (
    ColumnChoice,
    ImportSpec,
    coerce_cell,
    derive_key,
    infer_dtype,
)


@pytest.fixture()
def study(ctx, make_collection):
    make_collection("study")
    return "study"


def _csv(ctx, text: str, name: str = "people.csv"):
    ref = ctx.file_svc.store_bytes(text.encode(), name)
    return ref.sha256, ref.filename


def _xlsx(ctx, sheets: dict[str, list[list]], name: str = "people.xlsx"):
    import openpyxl

    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    ref = ctx.file_svc.store_bytes(out.getvalue(), name)
    return ref.sha256, ref.filename


def _spec(sha, name, inspected, *, kind="person", match=None, if_exists="update", **kw):
    columns = [
        ColumnChoice(
            heading=c.heading, field=c.key, create=True, dtype=c.dtype, label=c.label
        )
        for c in inspected.columns
    ]
    return ImportSpec(
        sha256=sha,
        filename=name,
        collection="study",
        kind=kind,
        kind_label="Person",
        columns=columns,
        match_on=match or [],
        if_exists=if_exists,
        **kw,
    )


def _people(ctx):
    return ctx.record_svc.find("study", schema_name="person", limit=100000)


# -- what a column looks like -------------------------------------------------


def test_types_are_inferred_without_losing_anything():
    assert infer_dtype(["1", "2", ""]) == "integer"
    assert infer_dtype(["1.5", "2", ""]) == "float"
    assert infer_dtype(["007", "012"]) == "string"  # an id, not a number
    assert infer_dtype(["007", "1.5"]) == "string"
    assert infer_dtype(["yes", "No"]) == "boolean"
    assert infer_dtype(["2024-01-05", "2024-02-30"]) == "string"  # not a date
    assert infer_dtype(["2024-01-05", "2024-01-05 00:00:00"]) == "date"
    assert infer_dtype(["2024-01-05 10:30:00"]) == "datetime"
    assert infer_dtype(["a" * 300]) == "longtext"
    assert infer_dtype(["", " "]) == "string"
    assert infer_dtype(["1e5"]) == "string"
    assert infer_dtype([str(10**20)]) != "integer"


def test_headings_become_keys_and_never_clash():
    taken: set[str] = set()
    keys = [
        derive_key(h, taken, i)
        for i, h in enumerate(["First Name!", "first name", "", "2nd", "ÄÖ"], 1)
    ]
    assert keys[0] == "first_name"
    assert keys[1] == "first_name_2"
    assert keys[2] == "column_3"
    assert keys[3] == "_2nd"
    assert len(set(keys)) == len(keys)
    for k in keys:
        assert k[0].isalpha() or k[0] == "_"


def test_a_cell_becomes_the_value_its_field_holds_or_says_why_not():
    assert coerce_cell("12", "integer") == 12
    assert coerce_cell("12.0", "integer") == 12
    assert coerce_cell("2024-01-05 00:00:00", "date") == "2024-01-05"
    assert coerce_cell("YES", "boolean") is True
    with pytest.raises(ValueError, match="'abc' is not a whole number"):
        coerce_cell("abc", "integer")
    with pytest.raises(ValueError, match="is not a date"):
        coerce_cell("05/01/2024", "date")


# -- looking inside -----------------------------------------------------------


def test_csv_is_looked_into(ctx):
    sha, name = _csv(
        ctx,
        "ID,First Name,Age,Weight,Active,Born,Notes\n"
        "007,Ann,31,60.5,yes,2024-01-05,hi\n"
        "012,Bob,,70,no,2024-02-06,\n",
    )
    seen = ctx.import_svc.inspect(sha, name)
    assert seen.total == 2 and seen.sheets == []
    by = {c.heading: c for c in seen.columns}
    assert by["ID"].dtype == "string" and by["ID"].key == "id"
    assert by["First Name"].key == "first_name"
    assert by["Age"].dtype == "integer" and by["Age"].blanks == 1
    assert by["Weight"].dtype == "float"
    assert by["Active"].dtype == "boolean"
    assert by["Born"].dtype == "date"
    assert seen.rows[0][0] == "007"  # shown as written


def test_blank_and_repeated_headings_are_handled(ctx):
    sha, name = _csv(ctx, "a,,a\n1,2,3\n")
    seen = ctx.import_svc.inspect(sha, name)
    assert [c.label for c in seen.columns][1] == "Column 2"
    assert len({c.key for c in seen.columns}) == 3


def test_semicolon_and_tab_files_are_read(ctx):
    sha, name = _csv(ctx, "a;b\n1;2\n", "x.csv")
    assert [c.heading for c in ctx.import_svc.inspect(sha, name).columns] == ["a", "b"]
    sha, name = _csv(ctx, "a\tb\n1\t2\n", "x.tsv")
    assert [c.heading for c in ctx.import_svc.inspect(sha, name).columns] == ["a", "b"]


def test_xlsx_is_looked_into_with_its_sheets_and_dates(ctx):
    import datetime as dt

    sha, name = _xlsx(
        ctx,
        {
            "People": [
                ["ID", "Age", "Born", "Seen"],
                ["007", 31, dt.datetime(2024, 1, 5), dt.datetime(2024, 1, 5, 10, 30)],
                ["012", None, dt.datetime(2024, 2, 6), dt.datetime(2024, 2, 6, 8, 0)],
            ],
            "Other": [["x"], [1]],
        },
    )
    seen = ctx.import_svc.inspect(sha, name)
    assert seen.sheets == ["People", "Other"] and seen.sheet == "People"
    by = {c.heading: c for c in seen.columns}
    assert by["ID"].dtype == "string"
    assert by["Age"].dtype == "integer"
    assert by["Born"].dtype == "date"
    assert by["Seen"].dtype == "datetime"
    other = ctx.import_svc.inspect(sha, name, "Other")
    assert [c.heading for c in other.columns] == ["x"]
    with pytest.raises(ValidationError, match="no sheet"):
        ctx.import_svc.inspect(sha, name, "Nope")


def test_a_file_that_is_not_there_or_not_a_table_is_refused(ctx):
    with pytest.raises(NotFoundError):
        ctx.import_svc.inspect("0" * 64, "x.csv")
    sha, name = _csv(ctx, "", "empty.csv")
    with pytest.raises(ValidationError):
        ctx.import_svc.inspect(sha, name)
    sha, name = _csv(ctx, "not excel", "broken.xlsx")
    with pytest.raises(ValidationError):
        ctx.import_svc.inspect(sha, name)


# -- saving -------------------------------------------------------------------

CSV = (
    "ID,Name,Age,Born\n"
    "007,Ann,31,2024-01-05\n"
    "012,Bob,,2024-02-06\n"
    "100,Cy,40,2024-03-07\n"
)


def test_a_new_kind_and_its_fields_are_made_from_the_headings(ctx, study):
    sha, name = _csv(ctx, CSV)
    seen = ctx.import_svc.inspect(sha, name)
    got = ctx.import_svc.run(_spec(sha, name, seen), 0, 1000)
    ctx.commit()
    assert (got.created, got.skipped, got.done) == (3, 0, True)
    fields = {f.name: f.dtype for f in ctx.schema_svc.get("person").fields}
    assert fields == {
        "id": "string",
        "name": "string",
        "age": "integer",
        "born": "date",
    }
    by_id = {r.data["id"]: r.data for r in _people(ctx)}
    assert set(by_id) == {"007", "012", "100"}  # the zeros are kept
    assert by_id["007"]["age"] == 31 and by_id["012"].get("age") is None
    assert by_id["100"]["born"] == "2024-03-07"


def test_a_type_chosen_by_the_user_wins(ctx, study):
    sha, name = _csv(ctx, CSV)
    seen = ctx.import_svc.inspect(sha, name)
    spec = _spec(sha, name, seen)
    spec = ImportSpec(
        **{
            **spec.__dict__,
            "columns": [
                ColumnChoice(**{**c.__dict__, "dtype": "string"})
                if c.heading == "Age"
                else c
                for c in spec.columns
            ],
        }
    )
    ctx.import_svc.run(spec, 0, 1000)
    assert {f.name: f.dtype for f in ctx.schema_svc.get("person").fields}["age"] == (
        "string"
    )


def test_xlsx_rows_are_saved_with_their_types(ctx, study):
    import datetime as dt

    sha, name = _xlsx(
        ctx,
        {
            "S": [
                ["ID", "Age", "Born"],
                ["007", 31, dt.datetime(2024, 1, 5)],
                [None, None, None],
                ["012", 40.0, dt.datetime(2024, 2, 6)],
            ]
        },
    )
    seen = ctx.import_svc.inspect(sha, name)
    got = ctx.import_svc.run(_spec(sha, name, seen), 0, 1000)
    ctx.commit()
    assert got.created == 2 and got.skipped == 0  # the empty row is nothing
    by_id = {r.data["id"]: r.data for r in _people(ctx)}
    assert by_id["012"]["age"] == 40 and by_id["007"]["born"] == "2024-01-05"


def _matched(ctx, sha, name, seen, **kw):
    return _spec(sha, name, seen, match=["id"], **kw)


def test_importing_again_updates_skips_or_adds_by_the_key(ctx, study):
    sha, name = _csv(ctx, CSV)
    seen = ctx.import_svc.inspect(sha, name)
    ctx.import_svc.run(_matched(ctx, sha, name, seen), 0, 1000)
    ctx.commit()

    again = ctx.import_svc.run(_matched(ctx, sha, name, seen), 0, 1000)
    assert (again.created, again.updated, again.unchanged) == (0, 0, 3)

    sha2, name2 = _csv(
        ctx, "ID,Name,Age,Born\n007,Ann,32,2024-01-05\n999,New,1,2024-01-01\n", "b.csv"
    )
    seen2 = ctx.import_svc.inspect(sha2, name2)
    check = ctx.import_svc.run(
        _matched(ctx, sha2, name2, seen2, if_exists="skip"), 0, 1000
    )
    assert (check.created, check.updated, check.skipped) == (1, 0, 1)
    assert "Row 2" in check.problems[0] and "left as it is" in check.problems[0]
    ctx.commit()
    assert {r.data["id"]: r.data.get("age") for r in _people(ctx)}["007"] == 31

    upd = ctx.import_svc.run(_matched(ctx, sha2, name2, seen2), 0, 1000)
    ctx.commit()
    assert (upd.created, upd.updated, upd.unchanged) == (0, 1, 1)
    assert {r.data["id"]: r.data.get("age") for r in _people(ctx)}["007"] == 32

    before = len(_people(ctx))
    ctx.import_svc.run(_matched(ctx, sha2, name2, seen2, if_exists="add_new"), 0, 1000)
    ctx.commit()
    assert len(_people(ctx)) == before + 2


def test_rows_that_cant_be_saved_are_named_plainly(ctx, study):
    sha, name = _csv(
        ctx,
        "ID,Age,Born\n1,31,2024-01-05\n2,abc,2024-01-05\n3,5,05/01/2024\n,7,2024-01-01\n"
        "1,9,2024-01-01\n",
    )
    seen = ctx.import_svc.inspect(sha, name)
    # a heading that looks like numbers but with one bad cell: the user keeps
    # the inferred types they were shown for ID, and chooses the others.
    spec = _matched(ctx, sha, name, seen)
    spec = ImportSpec(
        **{
            **spec.__dict__,
            "columns": [
                ColumnChoice(
                    **{
                        **c.__dict__,
                        "dtype": {"Age": "integer", "Born": "date"}.get(
                            c.heading, c.dtype
                        ),
                    }
                )
                for c in spec.columns
            ],
        }
    )
    got = ctx.import_svc.run(spec, 0, 1000)
    assert got.created == 1 and got.skipped == 4
    text = "\n".join(got.problems)
    assert "Row 3: age: 'abc' is not a whole number" in text
    assert "Row 4: born: '05/01/2024' is not a date" in text
    assert "Row 5: no id to match it by" in text
    assert "Row 6" in text and "is also row 2" in text


def test_a_value_the_field_refuses_is_named(ctx, study):
    ctx.schema_svc.create("person")
    ctx.schema_svc.add_field(
        "person", "age", "integer", restrictions={"min": 0, "max": 120}
    )
    ctx.commit()
    sha, name = _csv(ctx, "Age\n5\n500\n")
    spec = ImportSpec(
        sha256=sha,
        filename=name,
        collection="study",
        kind="person",
        columns=[ColumnChoice(heading="Age", field="age")],
    )
    got = ctx.import_svc.run(spec, 0, 1000)
    assert got.created == 1 and got.skipped == 1 and got.problems[0].startswith("Row 3")


def test_a_check_says_what_the_save_will_and_keeps_nothing(ctx, study):
    sha, name = _csv(ctx, CSV + "007,Dup,1,2024-01-01\n")
    seen = ctx.import_svc.inspect(sha, name)
    spec = _matched(ctx, sha, name, seen)
    checked = ctx.import_svc.run(spec, 0, 1000, check=True)
    assert [s.name for s in ctx.schema_svc.list_all()] == []  # not even the kind
    assert ctx.record_svc.find("study", limit=10) == []
    saved = ctx.import_svc.run(spec, 0, 1000)
    ctx.commit()
    assert checked == saved
    assert (saved.created, saved.skipped) == (3, 1)


def test_parts_of_a_file_give_what_the_whole_does(ctx, study):
    rows = ["ID,Age"] + [f"{i % 7},{i}" for i in range(40)] + ["x,abc"]
    sha, name = _csv(ctx, "\n".join(rows) + "\n")
    seen = ctx.import_svc.inspect(sha, name)

    def counts(parts: int, check: bool):
        spec = _spec(sha, name, seen, kind=f"k{parts}_{int(check)}", match=["id"])
        spec = ImportSpec(
            **{
                **spec.__dict__,
                "kind_label": "K",
                "columns": [
                    ColumnChoice(**{**c.__dict__, "dtype": "integer"})
                    if c.heading == "Age"
                    else c
                    for c in spec.columns
                ],
            }
        )
        total = dict(created=0, updated=0, unchanged=0, skipped=0)
        problems: list[str] = []
        size = -(-41 // parts)
        for start in range(0, 41, size):
            part = ctx.import_svc.run(spec, start, size, check=check)
            for k in total:
                total[k] += getattr(part, k)
            problems += part.problems
        return total, problems

    whole, whole_problems = counts(1, False)
    ctx.commit()
    for parts in (2, 5, 13):
        for check in (True, False):
            got, problems = counts(parts, check)
            assert got == whole, (parts, check)
            assert problems == whole_problems, (parts, check)
            ctx.commit()
    assert whole["skipped"] == 34  # 33 repeats of 7 keys, and the bad row
    assert any("Row 42: age: 'abc'" in p for p in whole_problems)
    assert any("is also row 2" in p for p in whole_problems)


def test_kinds_inside_another_record_are_refused(ctx, study):
    ctx.schema_svc.create("top")
    ctx.schema_svc.create("child", parent="top")
    ctx.commit()
    sha, name = _csv(ctx, "a\n1\n")
    spec = ImportSpec(
        sha256=sha,
        filename=name,
        collection="study",
        kind="child",
        columns=[ColumnChoice(heading="a", field="a", create=True)],
    )
    with pytest.raises(ValidationError, match="inside another record"):
        ctx.import_svc.run(spec, 0, 10)


def test_no_columns_or_two_in_one_field_is_refused(ctx, study):
    sha, name = _csv(ctx, "a,b\n1,2\n")
    base = dict(sha256=sha, filename=name, collection="study", kind="k", kind_label="K")
    with pytest.raises(ValidationError, match="at least one column"):
        ctx.import_svc.run(ImportSpec(columns=[ColumnChoice("a")], **base), 0, 10)
    with pytest.raises(ValidationError, match="Two columns"):
        ctx.import_svc.run(
            ImportSpec(
                columns=[
                    ColumnChoice("a", "x", create=True),
                    ColumnChoice("b", "x", create=True),
                ],
                **base,
            ),
            0,
            10,
        )


# -- a large file -------------------------------------------------------------


def test_a_large_file_is_looked_into_and_read_in_parts_quickly(ctx, study):
    n = 50_000
    lines = ["ID,Name,Age,Born"] + [
        f"{i:06d},name {i},{i % 90},2024-01-{i % 28 + 1:02d}" for i in range(n)
    ]
    sha, name = _csv(ctx, "\n".join(lines) + "\n", "big.csv")
    t = time.time()
    seen = ctx.import_svc.inspect(sha, name)
    assert seen.total == n
    assert [c.dtype for c in seen.columns] == ["string", "string", "integer", "date"]
    assert time.time() - t < 20
    # the last part of the file is reached without reading it into one table
    spec = _matched(ctx, sha, name, seen)
    t = time.time()
    got = ctx.import_svc.run(spec, n - 100, 5000, check=True)
    assert (got.read, got.created, got.done) == (100, 100, True)
    assert time.time() - t < 20
    assert ctx.import_svc.run(spec, n, 5000, check=True).read == 0


def test_ten_thousand_rows_are_brought_in_in_parts(ctx, study):
    n = 10_000
    lines = ["ID,Name,Age"] + [f"{i},name {i},{i % 90}" for i in range(n)]
    sha, name = _csv(ctx, "\n".join(lines) + "\n", "big.csv")
    seen = ctx.import_svc.inspect(sha, name)
    spec = _matched(ctx, sha, name, seen)
    t = time.time()
    created = 0
    for start in range(0, n, 5000):
        created += ctx.import_svc.run(spec, start, 5000).created
        ctx.commit()
    took = time.time() - t
    assert created == n
    assert took < 150  # about 4 ms a row; 50 000 rows take a few minutes


def test_a_run_that_saves_many_records_notes_each_once(ctx, study):
    """`WorkflowContext._note_affected` finds a record without walking the list
    (a large import once spent most of its time there), and still follows a
    list that was cleared."""
    from civex.plugins.base import WorkflowContext

    ctx.schema_svc.create("thing")
    ctx.commit()
    wf = WorkflowContext(record=None, dataset=None, _app_ctx=ctx)
    a = ctx.record_svc.add("study", "thing", {})
    b = ctx.record_svc.add("study", "thing", {})
    wf._note_affected(a, "created")
    wf._note_affected(b, "created")
    wf._note_affected(a, "updated")
    assert [(e["record_id"], e["action"]) for e in wf.affected_records] == [
        (str(a.id), "updated"),
        (str(b.id), "created"),
    ]
    wf.affected_records.clear()
    wf._note_affected(b, "updated")
    assert [e["action"] for e in wf.affected_records] == ["updated"]
