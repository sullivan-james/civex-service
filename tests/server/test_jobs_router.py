"""HTTP-level tests for /api/jobs."""

from __future__ import annotations

import uuid

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


def test_rerun_carries_forward_the_original_run_s_input_data(
    client: TestClient,
) -> None:
    """A manual run seeded with __input__ (e.g. a file the user attached)
    must survive a retry -- dropping it silently breaks any step that
    references __input__.<name>, with a confusing "unknown step" error
    instead of a clear one."""
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
    seeded_input = {"files": [{"sha256": "abc123", "filename": "f.csv", "size": 3}]}
    original = ctx.job_svc.enqueue_manual(
        "parse-audio-dates", record, input_data=seeded_input
    )
    ctx.commit()
    ctx.close()

    rerun_resp = client.post(f"/api/jobs/{original.id}/rerun")
    assert rerun_resp.status_code == 202

    ctx2 = build_local_context(load_config())
    new_job = ctx2.job_svc.get_job(uuid.UUID(rerun_resp.json()["id"]))
    assert new_job is not None
    assert new_job.input_data == seeded_input
    ctx2.close()


def _seed_runs(client: TestClient) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    client.put("/api/workflows/parse-audio-dates", json={"content": _VALID_YAML})
    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post("/api/collections", json={"name": "study", "description": None})
    rec = client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": {}},
    ).json()
    ctx = build_local_context(load_config())
    try:
        repo = ctx.job_svc._repo
        repo.enqueue("parse-audio-dates", uuid.UUID(rec["id"]), "manual")
        repo.enqueue("other-flow", uuid.UUID(rec["id"]), "record_created")
        ctx.commit()
    finally:
        ctx.close()


def test_runs_can_be_filtered_searched_and_sorted(client: TestClient) -> None:
    _seed_runs(client)

    manual = client.get("/api/jobs", params={"trigger": "manual"}).json()
    assert {j["trigger"] for j in manual} == {"manual"}
    assert client.get("/api/jobs/count", params={"trigger": "manual"}).json() == {
        "total": len(manual)
    }

    found = client.get("/api/jobs", params={"search": "other"}).json()
    assert {j["workflow_name"] for j in found} == {"other-flow"}

    names = [
        j["workflow_name"]
        for j in client.get("/api/jobs", params={"sort": "workflow_name:asc"}).json()
    ]
    assert names == sorted(names)
    newest_name_first = [
        j["workflow_name"]
        for j in client.get("/api/jobs", params={"sort": "workflow_name:desc"}).json()
    ]
    assert newest_name_first == sorted(names, reverse=True)


def _finished_runs(client: TestClient) -> dict[str, str]:
    """Four runs of one record: two failed (one with a step log), one
    completed and one still waiting. Returns their ids by role."""
    from civex.config import load_config
    from civex.context import build_local_context

    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post("/api/collections", json={"name": "study", "description": None})
    rec = client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": {}},
    ).json()
    record_id = uuid.UUID(rec["id"])
    step = {"step_id": "a", "plugin": "civex.get_field", "status": "failed"}
    ctx = build_local_context(load_config())
    try:
        repo = ctx.job_svc._repo
        ids = {}
        for role in ("failed", "failed_too", "completed", "waiting"):
            ids[role] = repo.enqueue(f"flow-{role}", record_id, "manual").id
        repo.mark_failed(
            ids["failed"], {"kind": "x", "message": "broke"}, step_executions=[step]
        )
        repo.mark_failed(ids["failed_too"], {"kind": "x", "message": "broke"})
        repo.mark_completed(ids["completed"])
        ctx.commit()
    finally:
        ctx.close()
    return {role: str(i) for role, i in ids.items()}


def test_deleting_every_failed_run_the_filter_matches(client: TestClient) -> None:
    ids = _finished_runs(client)
    failed = {"field": "status", "op": "eq", "value": "failed"}

    resp = client.post("/api/jobs/delete", json={"filter": failed})

    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}
    left = {j["id"] for j in client.get("/api/jobs").json()}
    assert left == {ids["completed"], ids["waiting"]}


def test_deleting_runs_by_id_whatever_their_state(client: TestClient) -> None:
    ids = _finished_runs(client)

    resp = client.post(
        "/api/jobs/delete", json={"ids": [ids["completed"], ids["waiting"]]}
    )

    assert resp.json() == {"deleted": 2}
    assert client.get(f"/api/jobs/{ids['waiting']}").status_code == 404
    assert client.get(f"/api/jobs/{ids['completed']}").status_code == 404


def test_deleting_runs_by_search_alone_and_refusing_nothing(
    client: TestClient,
) -> None:
    ids = _finished_runs(client)

    resp = client.post("/api/jobs/delete", json={"search": "failed_too"})

    assert resp.json()["deleted"] == 1
    assert client.get(f"/api/jobs/{ids['failed_too']}").status_code == 404
    assert client.post("/api/jobs/delete", json={}).status_code == 422


def test_deleting_every_run(client: TestClient) -> None:
    _finished_runs(client)

    resp = client.post("/api/jobs/delete", json={"every": True})

    assert resp.json() == {"deleted": 4}
    assert client.get("/api/jobs").json() == []
