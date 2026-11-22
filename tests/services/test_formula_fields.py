"""Formula fields: a value worked out from a record's other fields when it is
read (`RecordService._formula_results`), never stored, so nothing that stores
or sends a record (history, sync, bundles) can carry one, while everything
that shows or tabulates a record (API reads, explorer columns, table exports,
`frame`) does."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import event, select

from civex.context import AppContext
from civex.db.models import AuditLog
from civex.domain import bundle as spec
from civex.domain.exceptions import ValidationError
from civex.domain.query import RecordQuery
from civex.testing import Projects


@pytest.fixture()
def study(ctx: AppContext, make_collection):
    """site (area) -> patient (child of site: mass, height, start, end, bmi,
    stay, label, heavy), and a lab each patient links to."""
    s = ctx.schema_svc
    s.create("lab")
    s.add_field("lab", "code", "string")
    s.create("site")
    s.add_field("site", "name", "string")
    s.add_field("site", "area", "float")
    s.add_field("site", "half_area", "formula", restrictions={"expression": "area / 2"})
    s.create("patient", parent="site")
    s.add_field("patient", "tag", "string")
    s.add_field("patient", "mass", "float")
    s.add_field("patient", "height", "float")
    s.add_field("patient", "start", "date")
    s.add_field("patient", "end", "date")
    s.add_field("patient", "lab", "reference", restrictions={"schema": "lab"})
    s.add_field(
        "patient",
        "bmi",
        "formula",
        restrictions={"expression": "mass / height ** 2", "decimals": 1},
    )
    s.add_field(
        "patient",
        "stay",
        "formula",
        restrictions={"expression": "days_between(start, end)", "result": "integer"},
    )
    s.add_field(
        "patient",
        "label",
        "formula",
        restrictions={"expression": 'concat(name, "-", tag, "@", lab.code)'},
    )
    s.add_field(
        "patient",
        "heavy",
        "formula",
        restrictions={"expression": "bmi > 25"},
    )
    s.add_field(
        "patient",
        "per_area",
        "formula",
        restrictions={"expression": "mass / half_area"},
    )
    make_collection("study")
    r = ctx.record_svc
    lab = r.add("study", "lab", {"code": "L1"})
    site = r.add("study", "site", {"name": "North", "area": 10.0})
    p = r.add(
        "study",
        "patient",
        {
            "tag": "p1",
            "mass": 81.0,
            "height": 1.8,
            "start": "2024-01-01",
            "end": "2024-01-11",
            "lab": str(lab.id),
        },
        parent_record_id=str(site.id),
    )
    ctx.commit()
    return {"lab": lab, "site": site, "patient": p}


def test_the_result_type_is_worked_out_when_not_given(ctx: AppContext, study):
    fields = {f.name: f for f in ctx.schema_svc.get("patient").fields}
    assert fields["bmi"].restrictions["result"] == "float"
    assert fields["stay"].restrictions["result"] == "integer"
    assert fields["label"].restrictions["result"] == "string"
    assert fields["heavy"].restrictions["result"] == "boolean"


def test_formulas_are_worked_out_on_read_and_never_stored(ctx: AppContext, study):
    got = ctx.record_svc.get(str(study["patient"].id))
    assert got.derived["bmi"] == 25.0
    assert got.derived["stay"] == 10
    assert got.derived["label"] == "North-p1@L1"
    assert got.derived["heavy"] is False
    assert got.derived["per_area"] == 16.2  # through the site's own formula
    assert got.formula_errors is None
    for name in ("bmi", "stay", "label", "heavy", "per_area"):
        assert name not in got.data
    raw = ctx.record_svc.records_repo.get_by_id(study["patient"].id)
    formula_ids = {
        str(f.id) for f in ctx.schema_svc.get("patient").fields if f.dtype == "formula"
    }
    assert not formula_ids & set(raw.data)
    site = ctx.record_svc.get(str(study["site"].id))
    assert site.derived["half_area"] == 5.0


def test_a_change_shows_at_once_with_no_backfill(ctx: AppContext, study):
    ctx.schema_svc.update_field(
        "patient", "bmi", restrictions={"expression": "mass / height", "decimals": 0}
    )
    ctx.record_svc.patch(str(study["patient"].id), {"mass": 90.0})
    got = ctx.record_svc.get(str(study["patient"].id))
    assert got.derived["bmi"] == 50.0


def test_a_value_that_cant_be_worked_out_is_blank_with_a_note(ctx: AppContext, study):
    p = ctx.record_svc.add(
        "study",
        "patient",
        {"tag": "p2", "mass": 70.0, "height": 0.0},
        parent_record_id=str(study["site"].id),
    )
    got = ctx.record_svc.get(str(p.id))
    assert got.derived["bmi"] is None
    assert "divided by zero" in got.formula_errors["bmi"]
    # Blank inputs: blank, no note.
    assert got.derived["stay"] is None
    assert "stay" not in got.formula_errors
    # One record's problem doesn't stop a list.
    listed = ctx.record_svc.find("study", schema_name="patient")
    assert {r.derived["bmi"] for r in listed} == {25.0, None}


def test_values_sent_for_a_formula_are_dropped(ctx: AppContext, study):
    pid = str(study["patient"].id)
    ctx.record_svc.update(pid, {"mass": 81.0, "bmi": 999})
    raw = ctx.record_svc.records_repo.get_by_id(study["patient"].id)
    bmi = next(f for f in ctx.schema_svc.get("patient").fields if f.name == "bmi")
    assert str(bmi.id) not in raw.data
    with pytest.raises(ValidationError, match="formula"):
        ctx.record_svc.coerce_value("3", "formula", "bmi")
    result = ctx.record_svc.bulk_edit({"bmi": 3}, ids=[pid])
    assert result.changed == 0 and result.skipped == 1
    assert "formula" in result.skipped_records[0].reason


def test_lists_cant_be_filtered_or_sorted_by_a_formula(ctx: AppContext, study):
    with pytest.raises(ValidationError, match="filtered"):
        ctx.record_svc.query_records(
            RecordQuery(
                dataset="study",
                schema="patient",
                filter_tree={"field": "bmi", "op": "gt", "value": 1},
            )
        )
    with pytest.raises(ValidationError, match="sorted"):
        ctx.record_svc.query_records(
            RecordQuery(dataset="study", schema="patient", sort=[{"field": "bmi"}])
        )


@pytest.mark.parametrize(
    ("restrictions", "message"),
    [
        ({"expression": "weight * 2"}, "no field 'weight'"),
        ({"expression": "tag * 2"}, "needs a number"),
        ({"expression": "mass", "result": "date"}, "can't be shown as date"),
        ({"expression": "tag", "unit": "m"}, "only apply"),
        ({"expression": "x + 1"}, "can't use itself"),
        ({"expression": "lab * 2"}, "no field 'lab'"),
        ({"expression": "open('f')"}, "no function"),
        ({}, "needs an expression"),
        ({"expression": "1", "decimals": 99}, "0 to 10"),
    ],
)
def test_a_formula_that_cant_work_is_refused(
    ctx: AppContext, study, restrictions, message
):
    with pytest.raises(ValidationError, match=message):
        ctx.schema_svc.add_field("patient", "x", "formula", restrictions=restrictions)


def test_a_formula_cant_be_required_or_have_a_default(ctx: AppContext, study):
    with pytest.raises(ValidationError, match="required"):
        ctx.schema_svc.add_field(
            "patient", "x", "formula", required=True, restrictions={"expression": "1"}
        )
    with pytest.raises(ValidationError, match="default"):
        ctx.schema_svc.add_field(
            "patient",
            "x",
            "formula",
            default_value=1,
            restrictions={"expression": "1"},
        )


def test_formulas_cant_read_each_other_in_a_circle(ctx: AppContext, study):
    with pytest.raises(ValidationError, match="circle"):
        ctx.schema_svc.update_field(
            "patient", "bmi", restrictions={"expression": "1 if heavy else 2"}
        )
    with pytest.raises(ValidationError, match="itself"):
        ctx.schema_svc.update_field(
            "patient", "bmi", restrictions={"expression": "bmi + 1"}
        )


def test_a_link_reaches_stored_values_only(ctx: AppContext, study):
    ctx.schema_svc.add_field(
        "lab", "twice", "formula", restrictions={"expression": "concat(code, code)"}
    )
    with pytest.raises(ValidationError, match="lab.twice"):
        ctx.schema_svc.add_field(
            "patient", "x", "formula", restrictions={"expression": "lab.twice"}
        )


def test_a_formula_cant_be_in_a_name_template(ctx: AppContext, study):
    with pytest.raises(ValidationError):
        ctx.schema_svc.update("patient", display_template="{bmi}")


def test_renaming_a_field_rewrites_the_formulas_that_read_it(ctx: AppContext, study):
    ctx.schema_svc.update_field("patient", "mass", new_name="weight")
    ctx.schema_svc.update_field("site", "name", new_name="site_name")
    ctx.schema_svc.update_field("lab", "code", new_name="lab_code")
    ctx.schema_svc.update_field("patient", "bmi", new_name="index")
    ctx.commit()
    fields = {f.name: f for f in ctx.schema_svc.get("patient").fields}
    assert fields["index"].restrictions["expression"] == "weight / height ** 2"
    assert fields["heavy"].restrictions["expression"] == "index > 25"
    assert (
        fields["label"].restrictions["expression"]
        == 'concat(site_name, "-", tag, "@", lab.lab_code)'
    )
    assert fields["per_area"].restrictions["expression"] == "weight / half_area"
    got = ctx.record_svc.get(str(study["patient"].id))
    assert got.derived["index"] == 25.0 and got.derived["label"] == "North-p1@L1"
    # Each rewrite is an edit of that field, in history.
    entries = ctx._session.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == fields["heavy"].id, AuditLog.action == "update"
        )
    ).all()
    assert entries


def test_a_field_a_formula_reads_cant_be_deleted(ctx: AppContext, study):
    with pytest.raises(ValidationError, match="'bmi'"):
        ctx.schema_svc.delete_field("patient", "mass")
    with pytest.raises(ValidationError, match="'per_area'"):
        ctx.schema_svc.delete_field("site", "half_area")
    with pytest.raises(ValidationError, match="'label'"):
        ctx.schema_svc.delete_field("lab", "code")
    # One nothing reads can.
    ctx.schema_svc.delete_field("patient", "heavy")
    ctx.schema_svc.delete_field("patient", "bmi")


def test_history_holds_no_formula_value(ctx: AppContext, study):
    ctx.record_svc.update(str(study["patient"].id), {"mass": 90.0})
    ctx.commit()
    formula_ids = {
        str(f.id) for f in ctx.schema_svc.get("patient").fields if f.dtype == "formula"
    }
    rows = ctx._session.scalars(
        select(AuditLog).where(AuditLog.entity_id == study["patient"].id)
    ).all()
    assert rows
    for row in rows:
        text = json.dumps([row.old_data, row.new_data, row.delta])
        assert not any(fid in text for fid in formula_ids)
        assert "25.0" not in text


def test_a_bundle_carries_the_formula_not_its_values(
    ctx: AppContext, study, tmp_path: Path
):
    path = tmp_path / "b.civex.zip"
    ctx.bundle_svc.export(path)
    with zipfile.ZipFile(path) as zf:
        lines = [json.loads(x) for x in zf.read(spec.RECORDS).decode().splitlines()]
        manifest = json.loads(zf.read(spec.MANIFEST))
    patient = next(line for line in lines if line["schema"] == "patient")
    assert "bmi" not in patient["data"] and "label" not in patient["data"]
    patient_schema = next(s for s in manifest["schemas"] if s["name"] == "patient")
    assert any(f["name"] == "bmi" for f in patient_schema["fields"])

    projects = Projects(tmp_path / "others")
    try:
        other = projects("other")
        other.bundle_svc.import_bundle(path)
        other.commit()
        got = other.record_svc.get(str(study["patient"].id))
        assert got.derived["bmi"] == 25.0
        assert got.derived["label"] == "North-p1@L1"
    finally:
        projects.close()


def test_tables_and_frames_have_formula_columns(ctx: AppContext, study):
    ctx.schema_svc.add_field(
        "patient",
        "mass_lb",
        "formula",
        restrictions={"expression": "mass * 2.20462", "unit": "lb", "decimals": 1},
    )
    ctx.commit()
    rows = [
        row
        for page in ctx.file_access_svc.typed_rows(
            RecordQuery(dataset="study", schema="patient"),
            columns=["tag", "bmi", "stay", "mass_lb", "half_area"],
        )
        for row in page
    ]
    assert rows == [
        {"tag": "p1", "bmi": 25.0, "stay": 10, "mass_lb": 178.6, "half_area": 5.0}
    ]
    pd = pytest.importorskip("pandas")
    df = ctx.file_access_svc.frame(RecordQuery(dataset="study", schema="patient"))
    assert df["bmi"].dtype == "float64"
    assert str(df["stay"].dtype) == "Int64"
    assert df.attrs["units"]["mass_lb"] == "lb"
    assert df.attrs["types"]["heavy"] == "boolean"
    assert pd.notna(df["label"][0])


def test_explorer_columns_include_inherited_formulas(ctx: AppContext, study):
    listed = ctx.record_svc.query_records(
        RecordQuery(dataset="study", schema="patient"),
        columns=["bmi", "half_area", "name"],
    )
    assert listed[0].derived["bmi"] == 25.0
    assert listed[0].derived["half_area"] == 5.0
    assert listed[0].derived["name"] == "North"


def test_preview_works_a_formula_out_without_saving(ctx: AppContext, study):
    svc = ctx.record_svc
    preview = svc.preview_formula("patient", "mass * 2 + half_area")
    assert (preview.value, preview.result) == (167.0, "float")
    assert preview.record_id == study["patient"].id
    preview = svc.preview_formula(
        "patient", "mass / 0", record_id=str(study["patient"].id)
    )
    assert preview.value is None and "divided by zero" in preview.error
    preview = svc.preview_formula("patient", "nope + 1")
    assert "no field 'nope'" in preview.problem
    preview = svc.preview_formula("patient", "mass + 1", values={"mass": 2})
    assert preview.value == 3.0
    preview = svc.preview_formula("patient", "bmi + 1", field="bmi")
    assert "itself" in preview.problem
    assert ctx.schema_svc.get("patient").fields[-1].name == "per_area"


def _patients(ctx: AppContext, n: int) -> None:
    site = ctx.record_svc.add("study", "site", {"name": "S", "area": 4.0})
    for i in range(n):
        ctx.record_svc.add(
            "study",
            "patient",
            {"tag": f"x{i}", "mass": 50.0 + i, "height": 1.5},
            parent_record_id=str(site.id),
        )
    ctx.commit()


def test_a_page_of_formulas_costs_the_same_however_many_records(
    ctx: AppContext, study
) -> None:
    def statements_for(count: int) -> int:
        _patients(ctx, count)
        seen: list[str] = []
        engine = ctx._session.get_bind()

        def note(conn, cursor, statement, *args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", note)
        try:
            records = ctx.record_svc.find("study", schema_name="patient", limit=500)
        finally:
            event.remove(engine, "before_cursor_execute", note)
        assert all(r.derived and "per_area" in r.derived for r in records)
        return len(seen)

    assert statements_for(3) == statements_for(30)
