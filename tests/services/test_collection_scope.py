"""Collection scope (local/global), per-collection schema lists, and the rule
that a reference may only point into its own collection or a global one."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civex.context import AppContext
from civex.domain.exceptions import ValidationError


@pytest.fixture()
def species_schemas(make_schema):
    make_schema("species", fields=[("name", "string")])
    make_schema("sighting", fields=[("species", "reference"), ("note", "string")])


# --- creating and updating collections ---


def test_defaults_to_local_with_no_schemas(ctx: AppContext, make_collection):
    c = make_collection("study")
    assert c.scope == "local"
    assert c.schemas == []


def test_create_with_scope_and_schemas(ctx: AppContext, make_schema, make_collection):
    make_schema("species")
    c = make_collection("taxonomy", scope="global", schemas=["species"])
    assert (c.scope, c.schemas) == ("global", ["species"])


def test_invalid_scope_rejected(ctx: AppContext):
    with pytest.raises(ValidationError, match="scope"):
        ctx.dataset_svc.create("x", scope="everywhere")


def test_child_schema_needs_its_parent_listed(ctx: AppContext, make_schema):
    make_schema("deployment")
    make_schema("detection", parent="deployment")
    with pytest.raises(ValidationError, match="deployment"):
        ctx.dataset_svc.create("study", schemas=["detection"])


def test_add_schemas_brings_ancestors_and_is_idempotent(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("deployment")
    make_schema("detection", parent="deployment")
    make_collection("study")
    c = ctx.dataset_svc.add_schemas("study", ["detection"])
    assert c.schemas == ["deployment", "detection"]
    assert ctx.dataset_svc.add_schemas("study", ["detection"]).schemas == c.schemas


def test_cannot_remove_a_schema_that_has_records(
    ctx: AppContext, make_schema, make_collection, strict_schema_lists
):
    make_schema("species")
    make_collection("taxonomy", schemas=["species"])
    ctx.record_svc.add("taxonomy", "species", {})
    ctx.commit()
    with pytest.raises(ValidationError, match="still has records"):
        ctx.dataset_svc.update("taxonomy", schemas=[])


# --- the schema list gates record creation ---


def test_record_needs_an_enabled_schema(
    ctx: AppContext, make_schema, make_collection, strict_schema_lists
):
    make_schema("species")
    make_collection("taxonomy")
    with pytest.raises(ValidationError, match="not enabled"):
        ctx.record_svc.add("taxonomy", "species", {})
    ctx.dataset_svc.add_schemas("taxonomy", ["species"])
    assert ctx.record_svc.add("taxonomy", "species", {}).dataset_name == "taxonomy"


# --- the reference rule ---


def test_reference_within_own_collection(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    make_collection("study")
    sp = make_record("study", "species", {"name": "jaguar"})
    s = make_record("study", "sighting", {"species": str(sp.id)})
    assert s.reference_collections is None


def test_reference_into_global_collection_is_allowed_and_marked(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    make_collection("taxonomy", scope="global")
    make_collection("study")
    sp = make_record("taxonomy", "species", {"name": "jaguar"})
    s = make_record("study", "sighting", {"species": str(sp.id)})
    assert s.reference_collections == {str(sp.id): "taxonomy"}
    assert ctx.record_svc.get(str(s.id)).reference_collections == {
        str(sp.id): "taxonomy"
    }


def test_reference_into_another_local_collection_is_rejected(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    make_collection("lab")
    make_collection("study")
    sp = make_record("lab", "species", {"name": "jaguar"})
    with pytest.raises(ValidationError, match="local"):
        make_record("study", "sighting", {"species": str(sp.id)})


def test_reference_to_missing_record_is_rejected(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    import uuid

    make_collection("study")
    with pytest.raises(ValidationError, match="not found"):
        make_record("study", "sighting", {"species": str(uuid.uuid4())})


def test_update_accepts_an_unchanged_reference_echoed_back(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    make_collection("taxonomy", scope="global")
    make_collection("study")
    sp = make_record("taxonomy", "species", {"name": "jaguar"})
    s = make_record("study", "sighting", {"species": str(sp.id)})
    updated = ctx.record_svc.update(str(s.id), {"species": str(sp.id), "note": "x"})
    assert updated.data["note"] == "x"


# --- protecting a referenced global collection ---


def test_referenced_global_collection_cannot_go_local_or_be_deleted(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    make_collection("taxonomy", scope="global")
    make_collection("study")
    sp = make_record("taxonomy", "species", {"name": "jaguar"})
    make_record("study", "sighting", {"species": str(sp.id)})
    with pytest.raises(ValidationError, match="reference it"):
        ctx.dataset_svc.update("taxonomy", scope="local")
    with pytest.raises(ValidationError, match="reference it"):
        ctx.dataset_svc.delete("taxonomy")


def test_unreferenced_global_collection_can_go_local(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    make_collection("taxonomy", scope="global")
    make_record("taxonomy", "species", {"name": "jaguar"})
    assert ctx.dataset_svc.update("taxonomy", scope="local").scope == "local"


# --- reference search ---


def test_find_by_schema_reachable_from_skips_other_local_collections(
    ctx: AppContext, species_schemas, make_collection, make_record
):
    make_collection("taxonomy", scope="global")
    make_collection("lab")
    make_collection("study")
    make_record("taxonomy", "species", {"name": "global-one"})
    make_record("lab", "species", {"name": "lab-one"})
    make_record("study", "species", {"name": "own-one"})
    found = ctx.record_svc.find_by_schema("species", reachable_from="study")
    assert sorted(r.data["name"] for r in found) == ["global-one", "own-one"]
    assert {r.dataset_name for r in found} == {"taxonomy", "study"}


# --- HTTP ---


def test_api_round_trips_scope_and_schemas(client: TestClient):
    client.post("/api/schemas", json={"name": "species"})
    r = client.post(
        "/api/collections",
        json={"name": "taxonomy", "scope": "global", "schemas": ["species"]},
    )
    assert r.status_code == 201, r.text
    assert (r.json()["scope"], r.json()["schemas"]) == ("global", ["species"])
    r = client.patch("/api/collections/taxonomy", json={"scope": "local"})
    assert r.json()["scope"] == "local"
    assert (
        client.post(
            "/api/collections", json={"name": "bad", "schemas": ["nope"]}
        ).status_code
        == 404
    )
