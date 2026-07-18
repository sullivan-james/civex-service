"""HTTP-level tests for /api/workflows, backed by WorkflowService (CIVEX-54).
No prior test coverage existed for this router -- new coverage, not just
characterization.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

_VALID_YAML = """\
name: parse-audio-dates
description: A workflow
steps:
  - id: step-one
    plugin: civex.get_field
    config:
      field: subject
"""


def test_list_workflows_empty(client: TestClient) -> None:
    resp = client.get("/api/workflows")
    assert resp.status_code == 200
    assert resp.json() == []


def test_save_then_list_and_get(client: TestClient) -> None:
    put_resp = client.put(
        "/api/workflows/parse-audio-dates", json={"content": _VALID_YAML}
    )
    assert put_resp.status_code == 200
    body = put_resp.json()
    assert body["name"] == "parse-audio-dates"
    assert body["stem"] == "parse-audio-dates"
    assert body["content"] == _VALID_YAML

    list_resp = client.get("/api/workflows")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["name"] == "parse-audio-dates"

    get_resp = client.get("/api/workflows/parse-audio-dates")
    assert get_resp.status_code == 200
    assert get_resp.json()["content"] == _VALID_YAML


def test_save_rejects_bad_stem(client: TestClient) -> None:
    resp = client.put("/api/workflows/bad stem!", json={"content": _VALID_YAML})
    assert resp.status_code == 422


def test_save_rejects_invalid_yaml(client: TestClient) -> None:
    resp = client.put(
        "/api/workflows/parse-audio-dates", json={"content": "not: [valid"}
    )
    assert resp.status_code == 422


def test_get_unknown_stem_returns_404(client: TestClient) -> None:
    resp = client.get("/api/workflows/ghost")
    assert resp.status_code == 404


def test_delete_removes_workflow(client: TestClient) -> None:
    client.put("/api/workflows/parse-audio-dates", json={"content": _VALID_YAML})
    del_resp = client.delete("/api/workflows/parse-audio-dates")
    assert del_resp.status_code == 204
    assert client.get("/api/workflows").json() == []


def test_delete_unknown_stem_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/workflows/ghost")
    assert resp.status_code == 404


def test_run_unknown_workflow_returns_404(client: TestClient) -> None:
    resp = client.post("/api/workflows/ghost/run", json={"record_id": "x"})
    assert resp.status_code == 404
