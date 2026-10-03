"""HTTP contract for the name/label split on schemas and fields."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient


def test_create_schema_accepts_a_label(client: TestClient):
    response = client.post(
        "/api/schemas",
        json={"name": "acoustic_recording", "label": "Acoustic Recording"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["label"] == "Acoustic Recording"


def test_create_schema_rejects_a_non_slug_name(client: TestClient):
    response = client.post("/api/schemas", json={"name": "Acoustic Recording"})
    assert response.status_code == 422
    assert "acoustic_recording" in response.json()["detail"]


def test_label_is_null_when_unset(client: TestClient):
    client.post("/api/schemas", json={"name": "trial"})
    schema = client.get("/api/schemas/trial").json()
    assert schema["label"] is None


def test_create_schema_with_inline_fields_carries_their_labels(client: TestClient):
    response = client.post(
        "/api/schemas",
        json={
            "name": "trial",
            "fields": [
                {"name": "subject", "type": "string", "label": "Subject ID"},
                {"name": "notes", "type": "string"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    fields = {f["name"]: f["label"] for f in response.json()["fields"]}
    assert fields == {"subject": "Subject ID", "notes": None}


def test_add_field_accepts_a_label_and_rejects_a_non_slug_name(client: TestClient):
    client.post("/api/schemas", json={"name": "trial"})

    ok = client.post(
        "/api/schemas/trial/fields",
        json={"name": "recording_date", "type": "date", "label": "Recording Date"},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["label"] == "Recording Date"

    bad = client.post(
        "/api/schemas/trial/fields",
        json={"name": "Recording Date", "type": "date"},
    )
    assert bad.status_code == 422
    assert "recording_date" in bad.json()["detail"]


def test_patch_label_only_leaves_the_name_alone(client: TestClient):
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/schemas/trial/fields", json={"name": "subject", "type": "string"})

    schema_patch = client.patch("/api/schemas/trial", json={"label": "Clinical Trial"})
    assert schema_patch.status_code == 200, schema_patch.text
    assert schema_patch.json()["name"] == "trial"
    assert schema_patch.json()["label"] == "Clinical Trial"

    field_patch = client.patch(
        "/api/schemas/trial/fields/subject", json={"label": "Subject ID"}
    )
    assert field_patch.status_code == 200, field_patch.text
    assert field_patch.json() == {
        **field_patch.json(),
        "name": "subject",
        "label": "Subject ID",
    }


def test_patch_with_an_empty_label_clears_it(client: TestClient):
    client.post("/api/schemas", json={"name": "trial", "label": "Clinical Trial"})
    response = client.patch("/api/schemas/trial", json={"label": ""})
    assert response.status_code == 200, response.text
    assert response.json()["label"] is None


def test_patch_omitting_label_leaves_it_untouched(client: TestClient):
    client.post("/api/schemas", json={"name": "trial", "label": "Clinical Trial"})
    response = client.patch("/api/schemas/trial", json={"description": "Updated"})
    assert response.status_code == 200, response.text
    assert response.json()["label"] == "Clinical Trial"


def test_patch_rejects_renaming_to_a_non_slug(client: TestClient):
    client.post("/api/schemas", json={"name": "trial"})
    response = client.patch("/api/schemas/trial", json={"rename": "Clinical Trial"})
    assert response.status_code == 422


def test_patch_field_with_only_a_label_is_not_an_empty_update(client: TestClient):
    """label alone must satisfy the "provide at least one field" guard."""
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/schemas/trial/fields", json={"name": "subject", "type": "string"})
    response = client.patch(
        "/api/schemas/trial/fields/subject", json={"label": "Subject ID"}
    )
    assert response.status_code == 200, response.text


def test_dump_carries_labels(client: TestClient):
    client.post(
        "/api/schemas",
        json={
            "name": "trial",
            "label": "Clinical Trial",
            "fields": [{"name": "subject", "type": "string", "label": "Subject ID"}],
        },
    )
    dumped = client.get("/api/dump")
    assert dumped.status_code == 200, dumped.text
    doc = yaml.safe_load(dumped.text)  # the endpoint serves YAML, not JSON
    schema = next(s for s in doc["schemas"] if s["name"] == "trial")
    assert schema["label"] == "Clinical Trial"
    assert schema["fields"][0]["label"] == "Subject ID"
