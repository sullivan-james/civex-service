"""References to records that are deleted or no longer exist: the CLI and the
server say so plainly, rather than failing with a bare "not found"."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from civex.cli.utils import drain_jobs
from civex.context import AppContext
from civex.main import app

runner = CliRunner()


def _doc(ctx: AppContext, make_collection, make_schema, make_record):
    make_collection("study")
    make_schema("doc", fields=[("name", "string")])
    return make_record("study", "doc", {"name": "Secret"})


def test_history_of_a_deleted_record_is_found_by_a_prefix(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    record = _doc(ctx, make_collection, make_schema, make_record)
    ctx.record_svc.delete(str(record.id))
    ctx.commit()
    result = runner.invoke(app, ["history", "record", str(record.id)[:8]])
    assert result.exit_code == 0, result.output
    assert "delete" in result.output


def test_history_of_a_permanently_deleted_record_needs_its_whole_id_and_shows_the_tombstone(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    record = _doc(ctx, make_collection, make_schema, make_record)
    ctx.record_svc.delete(str(record.id))
    ctx.record_svc.purge(str(record.id))
    ctx.commit()

    whole = runner.invoke(app, ["history", "record", str(record.id)])
    assert whole.exit_code == 0, whole.output
    assert "purge" in whole.output
    assert "Secret" not in whole.output  # what it held is not kept

    short = runner.invoke(app, ["history", "record", str(record.id)[:8]])
    assert short.exit_code == 1
    assert "give its whole id" in short.output


def test_the_record_history_endpoint_answers_for_a_deleted_or_gone_record(
    client: TestClient,
) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study"})
    rid = client.post(
        "/api/collections/study/records", json={"schema_name": "trial", "data": {}}
    ).json()["id"]
    client.delete(f"/api/records/{rid}")
    assert client.get(f"/api/records/{rid}/audit").status_code == 200  # deleted
    client.delete(f"/api/records/{rid}/purge")
    body = client.get(f"/api/records/{rid}/audit")
    assert body.status_code == 200  # gone: the tombstone
    assert [i["action"] for i in body.json()["items"]] == ["purge"]


def test_the_runs_listing_says_when_a_runs_record_is_deleted(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    record = _doc(ctx, make_collection, make_schema, make_record)
    job = ctx.job_svc.enqueue_manual("noop", record)
    live = runner.invoke(app, ["automation", "jobs"], env={"COLUMNS": "240"})
    ctx.record_svc.delete(str(record.id))
    ctx.commit()
    gone = runner.invoke(app, ["automation", "jobs"], env={"COLUMNS": "240"})
    assert live.exit_code == 0 and gone.exit_code == 0, gone.output
    assert str(job.id)[:8] in gone.output
    assert "(deleted)" in gone.output and "(deleted)" not in live.output
    assert "Secret" in gone.output  # still named, so it can be recognised


def test_a_queued_run_for_a_deleted_record_fails_saying_why(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    record = _doc(ctx, make_collection, make_schema, make_record)
    wf_dir = ctx.workflow_svc._dir
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "fine.yaml").write_text(
        "name: fine\nsteps:\n  - id: read\n    plugin: civex.get_field\n    config: {field: name}\n"
    )
    job = ctx.job_svc.enqueue_manual("fine", record)
    ctx.record_svc.delete(str(record.id))
    ctx.commit()

    drain_jobs(ctx)

    finished = ctx.job_svc.get_job(job.id)
    assert finished is not None and finished.status == "failed"
    assert re.search(r"is deleted or no longer exists", finished.error or "")


def test_an_id_that_never_existed_is_not_found_not_an_empty_history(
    client: TestClient,
) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/records/{missing}/audit").status_code == 404
