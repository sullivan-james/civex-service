"""HTTP contract for a schema's record name template."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _trial(client: TestClient) -> None:
    client.post(
        "/api/schemas",
        json={
            "name": "trial",
            "fields": [
                {"name": "site", "type": "string"},
                {"name": "taken_on", "type": "date"},
            ],
        },
    )


def test_patch_sets_and_clears_the_template(client: TestClient):
    _trial(client)
    response = client.patch("/api/schemas/trial", json={"display_template": "{site}"})
    assert response.status_code == 200, response.text
    assert response.json()["display_template"] == "{site}"

    response = client.patch("/api/schemas/trial", json={"display_template": ""})
    assert response.json()["display_template"] is None


def test_patch_rejects_an_unknown_variable(client: TestClient):
    _trial(client)
    response = client.patch("/api/schemas/trial", json={"display_template": "{ghost}"})
    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]


def test_preview_renders_against_sample_values(client: TestClient):
    _trial(client)
    response = client.post(
        "/api/schemas/trial/preview-name",
        json={
            "template": "{site:upper}-{taken_on:YYYY-MM}",
            "values": {"site": "ridge", "taken_on": "2019-06-14"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"name": "RIDGE-2019-06", "error": None}


def test_preview_reports_a_bad_template_without_an_http_error(client: TestClient):
    _trial(client)
    response = client.post(
        "/api/schemas/trial/preview-name", json={"template": "{ghost}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] is None and "ghost" in body["error"]


def test_preview_of_a_file_name_offers_ext(client: TestClient):
    _trial(client)
    response = client.post(
        "/api/schemas/trial/preview-name",
        json={"template": "{site}.{ext}", "values": {"site": "a"}, "kind": "file"},
    )
    assert response.json()["name"] == "a.pdf"


def test_preview_of_an_unknown_schema_is_404(client: TestClient):
    response = client.post("/api/schemas/nope/preview-name", json={"template": "x"})
    assert response.status_code == 404
