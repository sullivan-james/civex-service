"""Stopping automation, cancelling a run, and what a run records about its cause.

The first test is the shape of a real incident: a workflow watching a file field
whose last step saves another field on the same record. It used to trigger itself
on every save, because the file looked changed each time."""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient

FILE = {"sha256": "a" * 64, "filename": "contour.csv", "size": 10}

WATCH_FILE = """\
name: compute
triggers:
  record_updated:
    schema: selection
    fields: [contour_file]
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: seed
  - id: save
    plugin: civex.save_field
    config:
      field: duration
    inputs:
      value: read.value
"""

WATCH_DURATION = """\
name: follow-up
triggers:
  record_updated:
    schema: selection
    fields: [duration]
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: duration
"""


def _setup(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "selection", "description": None})
    for name, dtype in (
        ("contour_file", "file"),
        ("seed", "float"),
        ("duration", "float"),
    ):
        r = client.post(
            "/api/schemas/selection/fields",
            json={"name": name, "type": dtype, "required": False},
        )
        assert r.status_code == 201, r.text
    client.post("/api/collections", json={"name": "study", "description": None})


def _jobs(client: TestClient) -> list[dict]:
    return client.get("/api/jobs?limit=100").json()


def _add_record(client: TestClient, **extra) -> dict:
    r = client.post(
        "/api/collections/study/records",
        json={
            "schema_name": "selection",
            "data": {"contour_file": FILE, "seed": 2.0, **extra},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_a_workflow_saving_another_field_does_not_trigger_itself(
    client: TestClient,
) -> None:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})

    record = _add_record(client)

    jobs = _jobs(client)
    assert [j["workflow_name"] for j in jobs] == ["compute"]  # one run, not a loop
    assert jobs[0]["status"] == "completed"
    saved = client.get(f"/api/records/{record['id']}").json()["data"]
    assert saved["duration"] == 2.0  # and it did its work


def test_a_run_says_which_field_started_it(client: TestClient) -> None:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})

    _add_record(client)

    (job,) = _jobs(client)
    detail = job["trigger_detail"]
    fields = {c["field"]: c for c in detail["changes"]}
    assert "contour_file" in fields
    assert fields["contour_file"]["watched"] is True
    assert fields["contour_file"]["after"] == "contour.csv"  # a file shows its name
    assert fields["seed"]["watched"] is False  # changed, but not what it watches
    assert detail["caused_by"] is None
    assert job["depth"] == 0


def test_a_run_started_by_another_runs_save_says_which_run(
    client: TestClient,
) -> None:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})
    client.put("/api/workflows/follow-up", json={"content": WATCH_DURATION})

    _add_record(client)

    by_name = {j["workflow_name"]: j for j in _jobs(client)}
    assert set(by_name) == {"compute", "follow-up"}
    follow = by_name["follow-up"]
    assert follow["depth"] == 1
    cause = follow["trigger_detail"]["caused_by"]
    assert cause == {"job_id": by_name["compute"]["id"], "workflow": "compute"}
    (change,) = [
        c for c in follow["trigger_detail"]["changes"] if c["field"] == "duration"
    ]
    assert change["before"] is None and change["after"] == "2.0"


def test_stop_pauses_automation_and_cancels_waiting_runs(
    client: TestClient,
) -> None:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})
    from civex.config import load_config
    from civex.context import build_local_context

    # Two waiting runs (queued directly: nothing drains them).
    ctx = build_local_context(load_config())
    rec = _add_record(client)
    record = ctx.record_svc.get(rec["id"])
    waiting = [ctx.job_svc.enqueue_manual("compute", record) for _ in range(2)]
    ctx.commit()
    ctx.close()

    stopped = client.post("/api/automation/stop")

    assert stopped.status_code == 200
    body = stopped.json()
    assert body["paused"] is True and body["cancelled"] == 2
    assert body["pending"] == 0 and body["running"] == 0
    for job in waiting:
        got = client.get(f"/api/jobs/{job.id}").json()
        assert got["status"] == "cancelled" and got["finished_at"]
    assert client.get("/api/automation").json()["paused"] is True


def test_while_paused_nothing_starts_and_manual_runs_are_refused(
    client: TestClient,
) -> None:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})
    client.post("/api/automation/stop")

    record = _add_record(client)  # would normally trigger the workflow

    assert _jobs(client) == []  # triggers enqueue nothing
    manual = client.post("/api/workflows/compute/run", json={"record_id": record["id"]})
    assert manual.status_code == 422
    assert "paused" in manual.json()["detail"].lower()


def test_resume_lets_triggers_fire_again(client: TestClient) -> None:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})
    client.post("/api/automation/stop")

    resumed = client.post("/api/automation/resume")
    assert resumed.json()["paused"] is False
    _add_record(client)

    assert [j["workflow_name"] for j in _jobs(client)] == ["compute"]


def test_a_single_run_can_be_cancelled(client: TestClient) -> None:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})
    from civex.config import load_config
    from civex.context import build_local_context

    ctx = build_local_context(load_config())
    rec = _add_record(client)
    job = ctx.job_svc.enqueue_manual("compute", ctx.record_svc.get(rec["id"]))
    ctx.commit()
    ctx.close()

    cancelled = client.post(f"/api/jobs/{job.id}/cancel")

    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    # Cancelling a finished run leaves it alone.
    done = _jobs(client)[-1]
    assert done["status"] == "completed"
    again = client.post(f"/api/jobs/{done['id']}/cancel")
    assert again.json()["status"] == "completed"


def test_cancelling_an_unknown_run_is_a_404(client: TestClient) -> None:
    assert client.post(f"/api/jobs/{uuid.uuid4()}/cancel").status_code == 404
    assert client.post("/api/jobs/nonsense/cancel").status_code == 400


def test_a_paused_drain_leaves_waiting_runs_alone(client: TestClient) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})
    ctx = build_local_context(load_config())
    rec = _add_record(client)
    ctx.job_svc.enqueue_manual("compute", ctx.record_svc.get(rec["id"]))
    ctx.commit()
    ctx.job_svc.set_paused(True)
    try:
        assert ctx.job_svc.claim_pending() is None  # the one gate every drain uses
    finally:
        ctx.close()
    time.sleep(0)


# -- filtering runs by workflow, and repeating several at once ------------------


def _two_workflows(client: TestClient) -> dict:
    _setup(client)
    client.put("/api/workflows/compute", json={"content": WATCH_FILE})
    client.put("/api/workflows/follow-up", json={"content": WATCH_DURATION})
    return _add_record(client)


def test_runs_can_be_filtered_to_one_workflow(client: TestClient) -> None:
    _two_workflows(client)  # one run of each: compute, then follow-up

    only = client.get("/api/jobs?workflow=compute").json()
    assert [j["workflow_name"] for j in only] == ["compute"]
    assert client.get("/api/jobs/count?workflow=follow-up").json() == {"total": 1}
    # Exactly the name, not a search: a part of it matches nothing.
    assert client.get("/api/jobs?workflow=comp").json() == []
    assert client.get("/api/jobs/count?workflow=nope").json() == {"total": 0}
    # And it combines with the other filters.
    both = client.get("/api/jobs?workflow=compute&status=completed").json()
    assert len(both) == 1


def test_several_runs_can_be_repeated_in_one_request(client: TestClient) -> None:
    _two_workflows(client)
    before = _jobs(client)
    ids = [j["id"] for j in before]

    resp = client.post("/api/jobs/rerun", json={"ids": ids})

    assert resp.status_code == 202
    body = resp.json()
    assert body["skipped"] == []
    assert sorted(j["workflow_name"] for j in body["started"]) == sorted(
        j["workflow_name"] for j in before
    )
    assert len(_jobs(client)) == len(before) * 2  # every one was repeated, once


def test_a_run_that_cannot_be_repeated_is_reported_and_the_rest_still_are(
    client: TestClient,
) -> None:
    record = _two_workflows(client)
    good = _jobs(client)[0]["id"]
    ghost = str(uuid.uuid4())

    resp = client.post("/api/jobs/rerun", json={"ids": [good, ghost, "nonsense", good]})

    body = resp.json()
    assert len(body["started"]) == 1  # the repeated id was only repeated once
    reasons = {s["id"]: s["reason"] for s in body["skipped"]}
    assert reasons[ghost] == "No such run."
    assert reasons["nonsense"] == "Not a run id."
    assert record["id"]  # (the record is still there)


def test_repeating_is_refused_while_paused_and_an_empty_request_is_invalid(
    client: TestClient,
) -> None:
    _two_workflows(client)
    ids = [j["id"] for j in _jobs(client)]
    client.post("/api/automation/stop")

    paused = client.post("/api/jobs/rerun", json={"ids": ids})
    assert paused.status_code == 422 and "paused" in paused.json()["detail"].lower()

    assert client.post("/api/jobs/rerun", json={"ids": []}).status_code == 422
    assert client.post("/api/jobs/rerun", json={"ids": ["x"] * 201}).status_code == 422
