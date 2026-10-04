"""CIVEX-169: reference/reference_list values are plain UUID strings inside the
JSON `data` blob, so no DB foreign key can protect them. RecordService must
detect referrers itself before letting a delete go through.
"""

from __future__ import annotations

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
import pytest


def test_delete_blocked_when_referenced_by_reference_field(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    visit = make_record("study", "visit", {"patient_ref": str(patient.id)})

    with pytest.raises(ValidationError, match="visit"):
        ctx.record_svc.delete(str(patient.id))

    # Nothing was actually deleted.
    assert ctx.record_svc.get(str(patient.id))
    assert ctx.record_svc.get(str(visit.id))


def test_delete_blocked_when_referenced_by_reference_list_field(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("cohort", fields=[("members", "reference_list")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    make_record("study", "cohort", {"members": [str(patient.id)]})

    with pytest.raises(ValidationError, match="cohort"):
        ctx.record_svc.delete(str(patient.id))


def test_delete_blocked_across_datasets(
    ctx: AppContext, make_schema, make_collection, make_record
):
    """A reference field isn't scoped to a dataset -- a record in another
    dataset can still be the thing blocking the delete."""
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study_a", scope="global")
    make_collection("study_b")

    patient = make_record("study_a", "patient", {})
    make_record("study_b", "visit", {"patient_ref": str(patient.id)})

    with pytest.raises(ValidationError, match="visit"):
        ctx.record_svc.delete(str(patient.id))


def test_delete_unreferenced_record_succeeds(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_collection("study")
    patient = make_record("study", "patient", {})

    ctx.record_svc.delete(str(patient.id))
    ctx.commit()

    with pytest.raises(Exception):
        ctx.record_svc.get(str(patient.id))


def test_delete_force_nulls_out_reference_field(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    visit = make_record("study", "visit", {"patient_ref": str(patient.id)})

    ctx.record_svc.delete(str(patient.id), force=True)
    ctx.commit()

    updated_visit = ctx.record_svc.get(str(visit.id))
    assert updated_visit.data["patient_ref"] is None


def test_delete_force_removes_from_reference_list_field(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("cohort", fields=[("members", "reference_list")])
    make_collection("study")

    p1 = make_record("study", "patient", {})
    p2 = make_record("study", "patient", {})
    cohort = make_record("study", "cohort", {"members": [str(p1.id), str(p2.id)]})

    ctx.record_svc.delete(str(p1.id), force=True)
    ctx.commit()

    updated_cohort = ctx.record_svc.get(str(cohort.id))
    assert updated_cohort.data["members"] == [str(p2.id)]


def test_delete_many_allows_references_within_the_same_batch(
    ctx: AppContext, make_schema, make_collection, make_record
):
    """Deleting a record and its only referrer together shouldn't block --
    both are disappearing, so the dangling-reference concern doesn't apply."""
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    visit = make_record("study", "visit", {"patient_ref": str(patient.id)})

    deleted = ctx.record_svc.delete_many([str(patient.id), str(visit.id)])
    ctx.commit()

    assert deleted == 2


def test_delete_many_blocked_when_referrer_outside_batch(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    other_patient = make_record("study", "patient", {})
    make_record("study", "visit", {"patient_ref": str(patient.id)})

    with pytest.raises(ValidationError, match="visit"):
        ctx.record_svc.delete_many([str(patient.id), str(other_patient.id)])


def test_delete_all_blocked_by_referrer_outside_scope(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    make_record("study", "visit", {"patient_ref": str(patient.id)})

    with pytest.raises(ValidationError, match="visit"):
        ctx.record_svc.delete_all("study", schema_name="patient")


def test_delete_all_force_nulls_out_referrers(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    visit = make_record("study", "visit", {"patient_ref": str(patient.id)})

    deleted = ctx.record_svc.delete_all("study", schema_name="patient", force=True)
    ctx.commit()

    assert deleted == 1
    assert ctx.record_svc.get(str(visit.id)).data["patient_ref"] is None


def test_find_dangling_references_surfaces_preexisting_violations(
    ctx: AppContext, make_schema, make_collection, make_record
):
    """A record deleted before this check existed (or via a direct repo write
    that bypassed RecordService) can leave a dangling reference behind --
    `find_dangling_references` is the audit that surfaces it."""
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    visit = make_record("study", "visit", {"patient_ref": str(patient.id)})

    # Bypass RecordService.delete() entirely, straight through the repository,
    # to simulate a dangling reference left over from before this ticket.
    ctx.record_svc._records.delete(patient.id)
    ctx.commit()

    dangling = ctx.record_svc.find_dangling_references()
    assert len(dangling) == 1
    entry = dangling[0]
    assert entry["record_id"] == visit.id
    assert entry["schema_name"] == "visit"
    assert entry["field_name"] == "patient_ref"
    assert entry["dangling_target_id"] == patient.id


def test_find_dangling_references_empty_when_consistent(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")

    patient = make_record("study", "patient", {})
    make_record("study", "visit", {"patient_ref": str(patient.id)})

    assert ctx.record_svc.find_dangling_references() == []


def test_referrer_counts_group_by_collection_schema_and_field(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_schema("cohort", fields=[("members", "reference_list")])
    make_collection("hub", scope="global")
    make_collection("study")

    patient = make_record("hub", "patient", {})
    other = make_record("hub", "patient", {})
    make_record("study", "visit", {"patient_ref": str(patient.id)})
    make_record("study", "visit", {"patient_ref": str(patient.id)})
    make_record("study", "visit", {"patient_ref": str(other.id)})
    make_record("study", "cohort", {"members": [str(patient.id), str(other.id)]})

    groups = ctx.record_svc.referrer_counts(str(patient.id))

    assert [
        (g.dataset_name, g.schema_name, g.field_name, g.dtype, g.count) for g in groups
    ] == [
        ("study", "cohort", "members", "reference_list", 1),
        ("study", "visit", "patient_ref", "reference", 2),
    ]
    assert ctx.record_svc.referrer_counts(str(other.id))[1].count == 1


def test_referrer_counts_ignores_deleted_referrers_and_includes_self(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("person", fields=[("friend", "reference")])
    make_collection("study")

    a = make_record("study", "person", {})
    b = make_record("study", "person", {"friend": str(a.id)})
    assert ctx.record_svc.referrer_counts(str(a.id))[0].count == 1

    ctx.record_svc.delete(str(b.id))
    assert ctx.record_svc.referrer_counts(str(a.id)) == []

    ctx.record_svc.update(str(a.id), {"friend": str(a.id)})
    assert ctx.record_svc.referrer_counts(str(a.id))[0].count == 1


def test_referrer_counts_skips_fields_restricted_to_another_schema(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("vet")
    make_schema("visit")
    ctx.schema_svc.add_field(
        "visit", "patient_ref", "reference", restrictions={"schema": "patient"}
    )
    ctx.schema_svc.add_field(
        "visit", "vet_ref", "reference", restrictions={"schema": "vet"}
    )
    ctx.commit()
    make_collection("study")

    patient = make_record("study", "patient", {})
    make_record("study", "visit", {"patient_ref": str(patient.id)})

    groups = ctx.record_svc.referrer_counts(str(patient.id))
    assert [(g.field_name, g.count) for g in groups] == [("patient_ref", 1)]


def _reference_rows(ctx: AppContext):
    from sqlalchemy import text

    return {
        tuple(r)
        for r in ctx._session.execute(
            text("SELECT record_id, target_id FROM record_references")
        )
    }


def test_reference_index_follows_every_way_a_reference_can_change(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_schema("cohort", fields=[("members", "reference_list")])
    make_collection("study")
    a = make_record("study", "patient", {})
    b = make_record("study", "patient", {})
    visit = make_record("study", "visit", {"patient_ref": str(a.id)})
    cohort = make_record("study", "cohort", {"members": [str(a.id), str(b.id)]})
    hex_ = lambda r: r.id.hex  # noqa: E731

    assert _reference_rows(ctx) == {
        (hex_(visit), hex_(a)),
        (hex_(cohort), hex_(a)),
        (hex_(cohort), hex_(b)),
    }

    ctx.record_svc.update(str(visit.id), {"patient_ref": str(b.id)})
    ctx.record_svc.update(str(cohort.id), {"members": [str(b.id)]})
    assert _reference_rows(ctx) == {
        (hex_(visit), hex_(b)),
        (hex_(cohort), hex_(b)),
    }

    ctx.record_svc.update(str(visit.id), {})  # field cleared
    assert _reference_rows(ctx) == {(hex_(cohort), hex_(b))}


def test_bulk_delete_blocked_then_allowed_with_a_large_batch(
    ctx: AppContext, make_schema, make_collection, make_record
):
    """More targets than fit one IN (...) chunk still find their referrer."""
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")
    patients = [make_record("study", "patient", {}) for _ in range(620)]
    make_record("study", "visit", {"patient_ref": str(patients[-1].id)})

    with pytest.raises(ValidationError, match="visit"):
        ctx.record_svc.delete_many([str(p.id) for p in patients])

    assert ctx.record_svc.delete_all("study", schema_name="visit") == 1
    assert ctx.record_svc.delete_many([str(p.id) for p in patients]) == 620
