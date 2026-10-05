"""Integration-level RecordService tests exercised through AppContext — the
reference-schema coercion check and the record_created/record_updated
dual-trigger-on-create behavior documented in CLAUDE.md.
"""

from __future__ import annotations

from civex.context import AppContext
from civex.domain.exceptions import CoercionError
import pytest


def test_reference_coercion_enforces_target_schema(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    # A "visit" record referenced where a "patient" is required should fail.
    visit = ctx.record_svc.add("study", "visit", {})
    ctx.commit()
    with pytest.raises(CoercionError, match="expected 'patient'"):
        ctx.record_svc.coerce_value(
            str(visit.id),
            "reference",
            "patient_ref",
            restrictions={"schema": "patient"},
        )


def test_reference_coercion_matching_schema_passes(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("patient")
    make_collection("study")
    patient = ctx.record_svc.add("study", "patient", {})
    ctx.commit()

    value = ctx.record_svc.coerce_value(
        str(patient.id), "reference", "patient_ref", restrictions={"schema": "patient"}
    )
    assert value == str(patient.id)


def test_field_restricted_trigger_only_fires_when_field_set_on_create(
    ctx: AppContext, make_schema, make_collection
):
    """A record_updated trigger scoped to `fields: [status]` must not fire on
    creation unless `status` was actually given a non-null value — otherwise
    field-restricted triggers would fire spuriously on every new record."""
    make_schema("trial", fields=[("subject", "string"), ("status", "string")])
    make_collection("study")

    workflows_dir = ctx.job_svc._civex_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "on_status.yaml").write_text(
        """
name: on_status
triggers:
  record_updated:
    schema: trial
    fields: [status]
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: status
"""
    )

    ctx.record_svc.add("study", "trial", {"subject": "S01"})
    ctx.commit()
    assert ctx.job_svc.count_jobs() == 0

    ctx.record_svc.add("study", "trial", {"subject": "S02", "status": "enrolled"})
    ctx.commit()
    assert ctx.job_svc.count_jobs() == 1


def _watch_file_field(ctx: AppContext) -> None:
    workflows_dir = ctx.job_svc._civex_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "on_scan.yaml").write_text(
        """
name: on_scan
triggers:
  record_updated:
    schema: invoice
    fields: [scan]
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: scan
"""
    )


def test_saving_another_field_does_not_trigger_a_workflow_watching_a_file_field(
    ctx: AppContext, make_schema, make_collection
):
    """A file value is shown with a derived `resolved_filename`, which is not
    stored. It must not make the file look edited: a workflow that watches the
    file and saves other fields on the same record (computing statistics from
    it, say) would otherwise trigger itself on every save, forever."""
    make_schema(
        "invoice",
        fields=[("invoice_number", "string"), ("scan", "file"), ("total", "float")],
    )
    ctx.schema_svc.update_field(
        "invoice", "scan", restrictions={"filename_template": "{invoice_number}.{ext}"}
    )
    make_collection("study")
    ref = {"sha256": "a" * 64, "filename": "upload.pdf", "size": 10}
    record = ctx.record_svc.add(
        "study", "invoice", {"invoice_number": "INV-42", "scan": ref}
    )
    ctx.commit()
    _watch_file_field(ctx)
    before = ctx.job_svc.count_jobs()

    # What a workflow does: read the record (derived key included), change an
    # unrelated field, and write the whole thing back.
    shown = ctx.record_svc.get(str(record.id)).data
    assert shown["scan"]["resolved_filename"] == "INV-42.pdf"
    ctx.record_svc.update(str(record.id), {**shown, "total": 12.5})
    ctx.commit()

    assert ctx.job_svc.count_jobs() == before  # the file didn't change: no run


def test_changing_the_file_itself_still_triggers_the_workflow(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("invoice", fields=[("scan", "file"), ("total", "float")])
    make_collection("study")
    old = {"sha256": "a" * 64, "filename": "one.pdf", "size": 10}
    record = ctx.record_svc.add("study", "invoice", {"scan": old})
    ctx.commit()
    _watch_file_field(ctx)
    before = ctx.job_svc.count_jobs()

    new = {"sha256": "b" * 64, "filename": "two.pdf", "size": 20}
    ctx.record_svc.update(str(record.id), {"scan": new})
    ctx.commit()

    assert ctx.job_svc.count_jobs() == before + 1


def test_the_audit_log_does_not_show_a_file_as_changed_when_it_was_not(
    ctx: AppContext, make_schema, make_collection
):
    make_schema(
        "invoice",
        fields=[("invoice_number", "string"), ("scan", "file"), ("total", "float")],
    )
    ctx.schema_svc.update_field(
        "invoice", "scan", restrictions={"filename_template": "{invoice_number}.{ext}"}
    )
    make_collection("study")
    ref = {"sha256": "a" * 64, "filename": "upload.pdf", "size": 10}
    record = ctx.record_svc.add(
        "study", "invoice", {"invoice_number": "INV-42", "scan": ref}
    )
    ctx.commit()

    shown = ctx.record_svc.get(str(record.id)).data
    ctx.record_svc.update(str(record.id), {**shown, "total": 3.0})
    ctx.commit()

    update = next(
        e for e in ctx.audit_svc.list_audit(entity_id=record.id) if e.action == "update"
    )
    # Entries are stored by field id.
    ids = {f.name: str(f.id) for f in ctx.schema_svc.get("invoice").fields}
    old, new = update.old_data["data"], update.new_data["data"]
    assert old[ids["scan"]] == new[ids["scan"]]  # same file, same stored value
    assert "resolved_filename" not in new[ids["scan"]]
    assert new[ids["total"]] == 3.0


def test_record_data_carries_resolved_filename_for_file_field(
    ctx: AppContext, make_schema, make_collection
):
    make_schema(
        "invoice",
        fields=[("invoice_number", "string"), ("scan", "file")],
    )
    ctx.schema_svc.update_field(
        "invoice", "scan", restrictions={"filename_template": "{invoice_number}.{ext}"}
    )
    make_collection("study")

    ref = {"sha256": "a" * 64, "filename": "upload.pdf", "size": 10}
    record = ctx.record_svc.add(
        "study", "invoice", {"invoice_number": "INV-42", "scan": ref}
    )
    ctx.commit()

    assert record.data["scan"]["filename"] == "upload.pdf"
    assert record.data["scan"]["resolved_filename"] == "INV-42.pdf"

    fetched = ctx.record_svc.get(str(record.id))
    assert fetched.data["scan"]["resolved_filename"] == "INV-42.pdf"


def test_record_data_file_field_falls_back_without_template(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("invoice", fields=[("scan", "file")])
    make_collection("study")

    ref = {"sha256": "a" * 64, "filename": "upload.pdf", "size": 10}
    record = ctx.record_svc.add("study", "invoice", {"scan": ref})
    ctx.commit()

    assert record.data["scan"]["resolved_filename"] == "upload.pdf"


def test_record_data_carries_resolved_filename_for_file_list_field(
    ctx: AppContext, make_schema, make_collection
):
    make_schema(
        "invoice",
        fields=[("invoice_number", "string"), ("scans", "file_list")],
    )
    ctx.schema_svc.update_field(
        "invoice", "scans", restrictions={"filename_template": "{invoice_number}.{ext}"}
    )
    make_collection("study")

    refs = [
        {"sha256": "a" * 64, "filename": "a.pdf", "size": 10},
        {"sha256": "b" * 64, "filename": "b.png", "size": 10},
    ]
    record = ctx.record_svc.add(
        "study", "invoice", {"invoice_number": "INV-7", "scans": refs}
    )
    ctx.commit()

    resolved = [item["resolved_filename"] for item in record.data["scans"]]
    assert resolved == ["INV-7.pdf", "INV-7.png"]
