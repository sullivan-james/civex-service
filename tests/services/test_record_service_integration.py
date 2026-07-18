"""Integration-level RecordService tests exercised through AppContext — the
reference-schema coercion check and the record_created/record_updated
dual-trigger-on-create behavior documented in CLAUDE.md.
"""
from __future__ import annotations

from civex.context import AppContext
from civex.domain.exceptions import CoercionError
import pytest


def test_reference_coercion_enforces_target_schema(ctx: AppContext, make_schema, make_collection):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    # A "visit" record referenced where a "patient" is required should fail.
    visit = ctx.record_svc.add("study", "visit", {})
    ctx.commit()
    with pytest.raises(CoercionError, match="expected 'patient'"):
        ctx.record_svc.coerce_value(
            str(visit.id), "reference", "patient_ref", restrictions={"schema": "patient"}
        )


def test_reference_coercion_matching_schema_passes(ctx: AppContext, make_schema, make_collection):
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

    workflows_dir = ctx.workflow_svc.workflows_dir
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
