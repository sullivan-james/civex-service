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
