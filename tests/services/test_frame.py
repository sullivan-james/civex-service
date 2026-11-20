"""Records as typed rows and DataFrames for scripts and notebooks
(`FileAccessService.typed_rows`/`frame`, `AppContext.rows`/`frame`): the table
an export writes, made by the same `table_rows`, with Python values instead of
text."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import event

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.domain.query import RecordQuery


@pytest.fixture()
def survey(ctx: AppContext, make_collection):
    """lab <- referenced by samples; site -> sample (a child kind)."""
    s = ctx.schema_svc
    s.create("lab")
    s.add_field("lab", "title", "string")
    s.create("site")
    s.add_field("site", "sname", "string")
    s.add_field("site", "region", "enum", restrictions={"choices": ["north", "south"]})
    s.add_field("site", "place", "geo")
    s.add_field("site", "photo", "file")
    s.create("sample", parent="site")
    s.add_field("sample", "code", "string")
    s.add_field("sample", "count", "integer")
    s.add_field("sample", "depth", "float", restrictions={"unit": "m"})
    s.add_field("sample", "ok", "boolean")
    s.add_field("sample", "taken", "datetime")
    s.add_field("sample", "day", "date")
    s.add_field("sample", "season", "date", restrictions={"precision": "year"})
    s.add_field("sample", "tags", "tags")
    s.add_field("sample", "audio", "file")
    s.add_field("sample", "extra", "file_list")
    s.add_field("sample", "lab", "reference", restrictions={"schema": "lab"})
    make_collection("survey")
    r = ctx.record_svc
    lab = r.add("survey", "lab", {"title": "Wet lab"})
    north = r.add(
        "survey",
        "site",
        {
            "sname": "North",
            "region": "north",
            "place": {"type": "Point", "coordinates": [-3.41, 56.12]},
            "photo": ctx.file_svc.store_bytes(b"jpeg", "north.jpg").to_dict(),
        },
    )
    south = r.add(
        "survey",
        "site",
        {
            "sname": "South",
            "region": "south",
            "place": {
                "type": "LineString",
                "coordinates": [[0, 0], [1, 1]],
            },
        },
    )
    audio = ctx.file_svc.store_bytes(b"wave", "a1.wav").to_dict()
    other = ctx.file_svc.store_bytes(b"notes", "notes.txt").to_dict()
    first = r.add(
        "survey",
        "sample",
        {
            "code": "S1",
            "count": 3,
            "depth": 1.5,
            "ok": True,
            "taken": "2024-06-14T09:30:00Z",
            "day": "2024-06-14",
            "season": "2024",
            "tags": ["a", "b"],
            "audio": audio,
            "extra": [other],
            "lab": str(lab.id),
        },
        parent_record_id=str(north.id),
    )
    second = r.add(
        "survey",
        "sample",
        {"code": "S2", "count": None, "depth": 2.0},
        parent_record_id=str(south.id),
    )
    ctx.commit()
    return {"lab": lab, "north": north, "south": south, "s1": first, "s2": second}


def _q(**kw) -> RecordQuery:
    return RecordQuery(dataset="survey", schema="sample", **kw)


def _by_code(rows: list[dict]) -> dict[str, dict]:
    return {r["code"]: r for r in rows}


def test_values_come_as_their_python_types(ctx: AppContext, survey):
    rows = _by_code(ctx.rows("survey", "sample"))
    s1 = rows["S1"]
    assert s1["id"] == str(survey["s1"].id)
    assert s1["count"] == 3 and isinstance(s1["count"], int)
    assert s1["depth"] == 1.5
    assert s1["ok"] is True
    assert s1["taken"] == datetime(2024, 6, 14, 9, 30, tzinfo=timezone.utc)
    assert s1["taken"].utcoffset().total_seconds() == 0
    assert s1["day"] == date(2024, 6, 14)
    # A field that takes a year keeps its values as written: 2024 is not a day.
    assert s1["season"] == "2024"
    assert s1["tags"] == ["a", "b"]
    assert rows["S2"]["count"] is None and rows["S2"]["ok"] is None


def test_the_fields_of_the_record_above_are_columns(ctx: AppContext, survey):
    rows = _by_code(ctx.rows("survey", "sample"))
    assert rows["S1"]["sname"] == "North"
    assert rows["S1"]["region"] == "north"
    assert rows["S2"]["sname"] == "South"


def test_record_columns(ctx: AppContext, survey):
    rows = ctx.rows(
        "survey",
        "sample",
        columns=["id", "schema", "parent_record_id", "created_at", "code"],
    )
    s1 = _by_code(rows)["S1"]
    assert list(s1) == ["id", "schema", "parent_record_id", "created_at", "code"]
    assert s1["schema"] == "sample"
    assert s1["parent_record_id"] == str(survey["north"].id)
    assert isinstance(s1["created_at"], datetime) and s1["created_at"].tzinfo


def test_locations_split_geojson_or_wkt(ctx: AppContext, survey):
    split = _by_code(ctx.rows("survey", "sample", columns=["code", "place"]))
    assert split["S1"]["place"] == {"type": "Point", "coordinates": [-3.41, 56.12]}
    assert (split["S1"]["place_lat"], split["S1"]["place_lon"]) == (56.12, -3.41)
    # A line has no single latitude.
    assert split["S2"]["place_lat"] is None
    assert split["S2"]["place"]["type"] == "LineString"

    plain = _by_code(
        ctx.rows("survey", "sample", columns=["code", "place"], geo="geojson")
    )
    assert list(plain["S1"]) == ["code", "place"]

    wkt = _by_code(ctx.rows("survey", "sample", columns=["code", "place"], geo="wkt"))
    assert wkt["S1"]["place"] == "POINT (-3.41 56.12)"
    assert wkt["S2"]["place"] == "LINESTRING (0 0, 1 1)"


def test_files_are_paths_on_this_computer_or_names(ctx: AppContext, survey):
    rows = _by_code(ctx.rows("survey", "sample", columns=["code", "audio", "extra"]))
    path = Path(rows["S1"]["audio"])
    assert path.is_absolute() and path.read_bytes() == b"wave"
    assert [Path(p).read_bytes() for p in rows["S1"]["extra"]] == [b"notes"]
    assert rows["S2"]["audio"] is None and rows["S2"]["extra"] is None
    # A file of the record above, found by its content.
    above = _by_code(ctx.rows("survey", "sample", columns=["code", "photo"]))
    assert Path(above["S1"]["photo"]).read_bytes() == b"jpeg"
    assert above["S2"]["photo"] is None

    named = _by_code(
        ctx.rows("survey", "sample", columns=["code", "audio", "extra"], files="name")
    )
    assert named["S1"]["audio"] == "a1.wav"
    assert named["S1"]["extra"] == ["notes.txt"]


def test_references_by_name_or_id(ctx: AppContext, survey):
    lab_id = str(survey["lab"].id)
    by_name = _by_code(ctx.rows("survey", "sample", columns=["code", "lab"]))
    assert by_name["S1"]["lab"] == "Wet lab"
    by_id = _by_code(
        ctx.rows("survey", "sample", columns=["code", "lab"], references="id")
    )
    assert by_id["S1"]["lab"] == lab_id
    joined = _by_code(ctx.rows("survey", "sample", columns=["code", "lab.title"]))
    assert joined["S1"]["lab.title"] == "Wet lab"
    assert joined["S2"]["lab.title"] is None


def test_filters_search_and_within_narrow_the_rows(ctx: AppContext, survey):
    assert [r["code"] for r in ctx.rows("survey", "sample", where=["code=S2"])] == [
        "S2"
    ]
    tree = {"field": "depth", "op": "gt", "value": 1.8}
    assert [r["code"] for r in ctx.rows("survey", "sample", where=tree)] == ["S2"]
    assert [r["code"] for r in ctx.rows("survey", "sample", search="S1")] == ["S1"]
    inside = ctx.rows("survey", "sample", within=str(survey["south"].id))
    assert [r["code"] for r in inside] == ["S2"]


def test_wrong_arguments_say_so_before_reading(ctx: AppContext, survey):
    with pytest.raises(ValidationError, match="nope"):
        ctx.rows("survey", "sample", columns=["code", "nope"])
    with pytest.raises(ValidationError, match="geo"):
        ctx.rows("survey", "sample", geo="kml")
    with pytest.raises(ValidationError, match="files"):
        ctx.rows("survey", "sample", files="bytes")
    with pytest.raises(ValidationError, match="schema"):
        ctx.file_access_svc.typed_rows(RecordQuery(dataset="survey"))


def test_a_frame_has_typed_columns_and_units(ctx: AppContext, survey):
    pd = pytest.importorskip("pandas")
    df = ctx.frame("survey", "sample").set_index("code")
    assert str(df["count"].dtype) == "Int64"
    assert df.loc["S2", "count"] is pd.NA
    assert df["depth"].dtype == "float64"
    assert str(df["ok"].dtype) == "boolean"
    assert isinstance(df["taken"].dtype, pd.DatetimeTZDtype)
    assert str(df["taken"].dt.tz) == "UTC"
    assert df.loc["S1", "taken"] == pd.Timestamp("2024-06-14T09:30:00Z")
    assert df["day"].dtype.kind == "M"
    assert df.loc["S1", "day"] == pd.Timestamp("2024-06-14")
    assert df.loc["S1", "season"] == "2024"
    assert str(df["region"].dtype) == "category"
    assert df.loc["S1", "place_lat"] == 56.12
    assert df.loc["S1", "tags"] == ["a", "b"]
    assert df.attrs["units"] == {"depth": "m"}
    assert df.attrs["types"]["taken"] == "datetime"


def test_an_empty_frame_still_has_its_columns(ctx: AppContext, survey):
    pytest.importorskip("pandas")
    df = ctx.frame("survey", "sample", where=["code=none"], columns=["code", "depth"])
    assert list(df.columns) == ["code", "depth"] and len(df) == 0


def test_without_pandas_the_error_says_how_to_get_it(
    ctx: AppContext, survey, monkeypatch
):
    monkeypatch.setitem(sys.modules, "pandas", None)
    with pytest.raises(ImportError, match="pip install pandas"):
        ctx.frame("survey", "sample")
    assert ctx.rows("survey", "sample")  # rows need nothing


def test_the_cost_does_not_grow_with_the_records(ctx: AppContext, survey):
    """Fields from the record above, a join, files and reference names are
    each looked up once a page, never once a record."""
    north, lab = survey["north"], survey["lab"]

    def count_for(n: int) -> int:
        for i in range(n):
            ref = ctx.file_svc.store_bytes(f"{n}-{i}".encode(), f"{i}.wav").to_dict()
            ctx.record_svc.add(
                "survey",
                "sample",
                {"code": f"N{n}-{i}", "audio": ref, "lab": str(lab.id)},
                parent_record_id=str(north.id),
            )
        ctx.commit()
        statements: list[str] = []
        engine = ctx._session.get_bind()

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            rows = ctx.rows(
                "survey",
                "sample",
                columns=["code", "sname", "place", "audio", "lab", "lab.title"],
            )
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert len(rows) >= n
        return len(statements)

    assert count_for(3) == count_for(30)
