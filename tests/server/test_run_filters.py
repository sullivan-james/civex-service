"""Filtering, grouping and tracking runs: the records' filter tree applied to
workflow runs, failures grouped by cause, and the batch the status bar follows."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from civex.config import load_config
from civex.context import build_local_context
from civex.domain.dtos import ErrorEnvelope

_YAML = "name: {n}\nsteps:\n  - id: s\n    plugin: civex.get_field\n    config:\n      field: subject\n"


def _f(field: str, op: str, value=None):
    return {"field": field, "op": op, "value": value}


def _q(tree) -> dict:
    return {"filter": json.dumps(tree)}


@pytest.fixture()
def runs(client: TestClient):
    """Six runs: a completed and two failed 'import' runs (one timeout, one
    validation, same message twice), a failed 'stats' run, a cancelled one and a
    waiting one."""
    for n in ("import", "stats"):
        client.put(f"/api/workflows/{n}", json={"content": _YAML.format(n=n)})
    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post(
        "/api/schemas/doc/fields",
        json={"name": "subject", "type": "string", "required": False},
    )
    client.post("/api/collections", json={"name": "study", "description": None})
    rec = client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": {"subject": "x"}},
    ).json()["id"]

    ctx = build_local_context(load_config())
    record = ctx.record_svc.get(rec)
    made: dict[str, uuid.UUID] = {}

    outcomes: list = []

    def run(key, workflow, outcome, message=None, kind=None, step="s"):
        # Queued now, finished afterwards: a bulk start queues every run before
        # the first one ends.
        job = ctx.job_svc.enqueue_manual(workflow, record)
        made[key] = job.id
        outcomes.append((job.id, outcome, message, kind, step))

    run("ok", "import", "completed")
    run("f1", "import", "failed", "Missing contour_file", "validation_error")
    run("f2", "import", "failed", "Missing contour_file", "validation_error")
    run("f3", "import", "failed", "took too long", "timeout", step="load")
    run("g1", "stats", "failed", "Missing contour_file", "validation_error")
    run("c1", "stats", "cancelled")
    run("w1", "stats", "pending")
    for job_id, outcome, message, kind, step in outcomes:
        if outcome == "completed":
            ctx.job_svc.mark_completed(
                job_id, log=None, step_executions=None, affected_records=[]
            )
        elif outcome == "failed":
            ctx.job_svc.mark_failed(
                job_id,
                ErrorEnvelope(kind=kind, message=message, step=step),
                log=None,
                step_executions=None,
                affected_records=None,
            )
        elif outcome == "cancelled":
            ctx.job_svc.cancel_job(job_id)
    ctx.commit()
    ctx.close()
    return made


def _ids(client, tree, **extra) -> set[str]:
    r = client.get("/api/jobs", params={**_q(tree), "limit": 500, **extra})
    assert r.status_code == 200, r.text
    return {j["id"] for j in r.json()}


def test_the_same_filter_tree_as_records_narrows_runs(client, runs) -> None:
    failed = _ids(client, _f("status", "eq", "failed"))
    assert failed == {str(runs[k]) for k in ("f1", "f2", "f3", "g1")}

    both = _ids(
        client,
        {"and": [_f("status", "eq", "failed"), _f("workflow", "eq", "import")]},
    )
    assert both == {str(runs[k]) for k in ("f1", "f2", "f3")}

    either = _ids(
        client, {"or": [_f("status", "eq", "cancelled"), _f("status", "eq", "pending")]}
    )
    assert either == {str(runs[k]) for k in ("c1", "w1")}

    not_failed = _ids(client, _f("status", "ne", "failed"))
    assert not_failed == {str(runs[k]) for k in ("ok", "c1", "w1")}

    several = _ids(client, _f("status", "in", ["cancelled", "completed"]))
    assert several == {str(runs[k]) for k in ("ok", "c1")}


def test_filters_on_why_a_run_failed(client, runs) -> None:
    assert _ids(client, _f("error_kind", "eq", "timeout")) == {str(runs["f3"])}
    assert _ids(client, _f("failed_step", "eq", "load")) == {str(runs["f3"])}
    contains = _ids(client, _f("error", "contains", "contour"))
    assert contains == {str(runs[k]) for k in ("f1", "f2", "g1")}  # case blind too
    assert _ids(client, _f("error", "contains", "CONTOUR")) == contains
    assert _ids(client, _f("schema", "eq", "doc")) == {str(v) for v in runs.values()}


def test_filters_on_when(client, runs) -> None:
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert _ids(client, _f("created_at", "gte", future)) == set()
    assert len(_ids(client, _f("created_at", "gte", past))) == len(runs)
    assert _ids(client, _f("finished_at", "is_null", True)) == {str(runs["w1"])}
    # a "Z" date, as a browser writes it
    assert len(
        _ids(client, _f("created_at", "lt", future.replace("+00:00", "Z")))
    ) == len(runs)


def test_count_and_list_agree_and_a_bad_filter_is_a_clear_422(client, runs) -> None:
    tree = _f("status", "eq", "failed")
    assert client.get("/api/jobs/count", params=_q(tree)).json() == {"total": 4}

    for bad, hint in [
        (_f("nope", "eq", 1), "Unknown run field"),
        (_f("status", "gt", 1), "doesn't apply"),
        (
            {"field": "status", "op": "eq", "value": "x", "schema": "doc"},
            "can't name a schema",
        ),
    ]:
        r = client.get("/api/jobs", params=_q(bad))
        assert r.status_code == 422 and hint in r.text, r.text
    assert client.get("/api/jobs", params={"filter": "{not json"}).status_code == 422


def test_it_combines_with_search_and_the_other_filters(client, runs) -> None:
    got = _ids(client, _f("status", "eq", "failed"), workflow="stats")
    assert got == {str(runs["g1"])}


def test_failures_group_by_what_went_wrong(client, runs) -> None:
    groups = client.get("/api/jobs/failure-groups").json()
    top = groups[0]
    # three runs say "Missing contour_file" - two in one workflow, one in another
    assert (top["workflow"], top["message"], top["count"]) == (
        "import",
        "Missing contour_file",
        2,
    )
    assert sum(g["count"] for g in groups) == 4  # only failed runs, all counted once
    assert {(g["workflow"], g["kind"]) for g in groups} == {
        ("import", "validation_error"),
        ("import", "timeout"),
        ("stats", "validation_error"),
    }
    timeout = next(g for g in groups if g["kind"] == "timeout")
    assert timeout["step"] == "load" and timeout["count"] == 1

    # narrowed by the same filter
    only = client.get(
        "/api/jobs/failure-groups", params=_q(_f("workflow", "eq", "stats"))
    ).json()
    assert [(g["workflow"], g["count"]) for g in only] == [("stats", 1)]


def test_filters_run_filter_fields_are_served_for_the_ui(client) -> None:
    fields = client.get("/api/jobs/filter-fields").json()
    by = {f["name"]: f for f in fields}
    assert by["status"]["choices"] == [
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    assert (
        by["created_at"]["type"] == "datetime"
        and "gte" in by["created_at"]["operators"]
    )
    assert "contains" in by["error"]["operators"]


def test_rerun_everything_a_filter_matches_in_one_request(client, runs) -> None:
    r = client.post("/api/jobs/rerun", json={"filter": _f("status", "eq", "failed")})

    assert r.status_code == 202, r.text
    assert len(r.json()["started"]) == 4
    # the originals are still there, and four new runs joined them
    assert client.get("/api/jobs/count").json()["total"] == len(runs) + 4


def test_rerun_needs_exactly_one_of_ids_or_filter(client, runs) -> None:
    assert client.post("/api/jobs/rerun", json={}).status_code == 422
    both = {"ids": [str(runs["f1"])], "filter": _f("status", "eq", "failed")}
    assert client.post("/api/jobs/rerun", json=both).status_code == 422


def test_batch_counts_every_run_in_the_stretch_not_just_what_the_first_poll_saw(
    client, runs
) -> None:
    # One run is still waiting, and the rest were queued while something was
    # unfinished: all seven are one batch, with the outcome of each so far.
    batch = client.get("/api/automation").json()["batch"]
    assert batch is not None
    assert batch["total"] == 7 and batch["active"] == 1
    assert (batch["completed"], batch["failed"], batch["cancelled"]) == (1, 4, 1)


def test_batch_is_gone_when_the_queue_is_empty(client, runs) -> None:
    client.post("/api/automation/stop")
    client.post("/api/automation/resume")
    # nothing waiting any more (the stop cancelled the waiting run)
    assert client.get("/api/automation").json()["batch"] is None


def test_an_old_finished_run_is_not_part_of_a_new_batch(client) -> None:
    client.put("/api/workflows/import", json={"content": _YAML.format(n="import")})
    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post(
        "/api/schemas/doc/fields",
        json={"name": "subject", "type": "string", "required": False},
    )
    client.post("/api/collections", json={"name": "study", "description": None})
    rec = client.post(
        "/api/collections/study/records", json={"schema_name": "doc", "data": {}}
    ).json()["id"]
    ctx = build_local_context(load_config())
    record = ctx.record_svc.get(rec)
    old = ctx.job_svc.enqueue_manual("import", record)
    ctx.job_svc.mark_completed(
        old.id, log=None, step_executions=None, affected_records=[]
    )
    ctx.commit()
    ctx.close()
    # a run finished, the queue emptied, and only then did a new one arrive
    import time

    time.sleep(0.05)
    ctx = build_local_context(load_config())
    ctx.job_svc.enqueue_manual("import", ctx.record_svc.get(rec))
    ctx.commit()
    ctx.close()

    batch = client.get("/api/automation").json()["batch"]

    assert batch["total"] == 1 and batch["completed"] == 0
