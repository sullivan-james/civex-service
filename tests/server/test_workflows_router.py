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


def test_get_workflow_includes_a_readable_step_summary(client: TestClient) -> None:
    """CIVEX-263: the UI renders steps/inputs/outputs without parsing YAML
    itself, so the detail response carries a structured step list alongside
    the raw `content`."""
    content = """\
name: two-step
description: A workflow
triggers:
  record_created:
    schema: doc
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: subject
  - id: save
    plugin: civex.save_field
    config:
      field: title
    inputs:
      value: read.value
"""
    client.put("/api/workflows/two-step", json={"content": content})
    resp = client.get("/api/workflows/two-step")
    assert resp.status_code == 200
    body = resp.json()
    assert body["step_list"] == [
        {
            "id": "read",
            "plugin": "civex.get_field",
            "config": {"field": "subject"},
            "inputs": {},
            "condition": None,
        },
        {
            "id": "save",
            "plugin": "civex.save_field",
            "config": {"field": "title"},
            "inputs": {"value": "read.value"},
            "condition": None,
        },
    ]
    assert body["triggers"] == {
        "record_created": {"schema_name": "doc", "fields": None}
    }


def test_save_rejects_bad_stem(client: TestClient) -> None:
    resp = client.put("/api/workflows/bad stem!", json={"content": _VALID_YAML})
    assert resp.status_code == 422


def test_save_rejects_invalid_yaml(client: TestClient) -> None:
    resp = client.put(
        "/api/workflows/parse-audio-dates", json={"content": "not: [valid"}
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str)


def test_save_rejects_a_contract_violation_with_structured_per_step_errors(
    client: TestClient,
) -> None:
    """CIVEX-109: a plugin/config/input-reference violation returns a list
    of {step, message} instead of one flattened exception string, so a UI
    can point at the offending step directly."""
    resp = client.put(
        "/api/workflows/broken",
        json={
            "content": """\
name: broken
steps:
  - id: one
    plugin: civex.get_field
    config:
      field: subject
      fileds: subject
"""
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail == [
        {
            "step": "one",
            "message": (
                "Step 'one' config has unknown key 'fileds' for plugin "
                "'civex.get_field' (accepts: field)"
            ),
        }
    ]


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


def test_delete_blocked_by_pending_job_returns_409(client: TestClient) -> None:
    """Enqueues the job directly against the same on-disk project rather
    than via POST .../run -- TestClient executes FastAPI BackgroundTasks
    synchronously before the request returns, so a /run call would drain
    the job to 'completed' before delete ever saw it as pending."""
    from civex.config import load_config
    from civex.context import build_local_context

    client.put("/api/workflows/parse-audio-dates", json={"content": _VALID_YAML})
    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post(
        "/api/schemas/doc/fields",
        json={"name": "subject", "type": "string", "required": False},
    )
    client.post("/api/collections", json={"name": "study", "description": None})
    rec_resp = client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": {"subject": "x"}},
    )
    record_id = rec_resp.json()["id"]

    ctx = build_local_context(load_config())
    record = ctx.record_svc.get(record_id)
    ctx.job_svc.enqueue_manual("parse-audio-dates", record)
    ctx.commit()
    ctx.close()

    del_resp = client.delete("/api/workflows/parse-audio-dates")
    assert del_resp.status_code == 409

    force_resp = client.delete("/api/workflows/parse-audio-dates?force=true")
    assert force_resp.status_code == 204
