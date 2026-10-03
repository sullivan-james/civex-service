"""HTTP contract for /api/analytics/*, the aggregate/time-bucketed read
path dashboard widgets call. Exercises the shared filter contract
(dataset/schema/date-range/plugin_id/etc.) end to end through the same
create/run flows other server tests use, rather than poking the service
directly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

_FAILING_YAML = """\
name: failing
steps:
  - id: load-the-attachment
    plugin: civex.load_file
    config: {field: attachment}
"""

_FINE_YAML = """\
name: fine
steps:
  - id: read
    plugin: civex.get_field
    config: {field: name}
"""


def _setup_schema_and_collection(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "doc"})
    client.post("/api/schemas/doc/fields", json={"name": "name", "type": "string"})
    client.post("/api/schemas/doc/fields", json={"name": "attachment", "type": "file"})
    client.post("/api/collections", json={"name": "study"})


def _make_record(client: TestClient, data: dict) -> str:
    resp = client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": data},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_record_counts_by_dataset_and_schema(client: TestClient) -> None:
    _setup_schema_and_collection(client)
    _make_record(client, {"name": "alice"})
    _make_record(client, {"name": "bob"})

    resp = client.get("/api/analytics/records/counts", params={"dataset": "study"})
    assert resp.status_code == 200
    assert resp.json() == {
        "items": [{"dataset": "study", "schema_name": "doc", "count": 2}]
    }

    # Unscoped -- same total, discovered across every dataset.
    resp = client.get("/api/analytics/records/counts")
    assert resp.json()["items"] == [
        {"dataset": "study", "schema_name": "doc", "count": 2}
    ]


def test_record_counts_unknown_dataset_returns_404(client: TestClient) -> None:
    resp = client.get("/api/analytics/records/counts", params={"dataset": "ghost"})
    assert resp.status_code == 404


def test_record_growth_is_bucketed_by_day(client: TestClient) -> None:
    _setup_schema_and_collection(client)
    _make_record(client, {"name": "alice"})
    _make_record(client, {"name": "bob"})

    resp = client.get(
        "/api/analytics/records/growth", params={"dataset": "study", "schema": "doc"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "day"
    assert len(body["items"]) == 1
    point = body["items"][0]
    assert point["dataset"] == "study"
    assert point["schema_name"] == "doc"
    assert point["count"] == 2


def test_record_growth_unknown_schema_returns_404(client: TestClient) -> None:
    _setup_schema_and_collection(client)
    resp = client.get("/api/analytics/records/growth", params={"schema": "ghost"})
    assert resp.status_code == 404


def _run_workflows(client: TestClient) -> None:
    """Two failing runs of a plugin that raises, one successful run of a
    different plugin -- mirrors test_failure_counts_by_plugin_aggregates_
    across_jobs, but end to end through the HTTP run endpoint (TestClient
    runs the drain BackgroundTask synchronously, so jobs are settled by the
    time /run returns)."""
    client.put("/api/workflows/failing", json={"content": _FAILING_YAML})
    client.put("/api/workflows/fine", json={"content": _FINE_YAML})

    for _ in range(2):
        record_id = _make_record(client, {"name": "x"})
        resp = client.post("/api/workflows/failing/run", json={"record_id": record_id})
        assert resp.status_code == 202

    fine_id = _make_record(client, {"name": "alice"})
    resp = client.post("/api/workflows/fine/run", json={"record_id": fine_id})
    assert resp.status_code == 202


def test_job_status_counts(client: TestClient) -> None:
    _setup_schema_and_collection(client)
    _run_workflows(client)

    resp = client.get("/api/analytics/jobs/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "day"
    by_status = {item["status"]: item["count"] for item in body["items"]}
    assert by_status == {"failed": 2, "completed": 1}


def test_job_status_counts_filters_by_workflow_id_and_trigger(
    client: TestClient,
) -> None:
    _setup_schema_and_collection(client)
    _run_workflows(client)

    resp = client.get(
        "/api/analytics/jobs/status",
        params={"workflow_id": "fine", "trigger": "manual"},
    )
    items = resp.json()["items"]
    assert items == [{"bucket": items[0]["bucket"], "status": "completed", "count": 1}]


def test_plugin_failure_counts_generalizes_the_worker_stats_aggregate(
    client: TestClient,
) -> None:
    _setup_schema_and_collection(client)
    _run_workflows(client)

    resp = client.get("/api/analytics/jobs/failures-by-plugin")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "day"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["plugin"] == "civex.load_file"
    assert item["count"] == 2

    # Narrowed to a plugin that never failed.
    resp = client.get(
        "/api/analytics/jobs/failures-by-plugin",
        params={"plugin_id": "civex.get_field"},
    )
    assert resp.json()["items"] == []


def test_job_duration_stats(client: TestClient) -> None:
    _setup_schema_and_collection(client)
    _run_workflows(client)

    resp = client.get("/api/analytics/jobs/duration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3  # 2 failed load_file steps + 1 successful get_field step
    assert body["avg_seconds"] is not None
    assert body["min_seconds"] is not None
    assert body["max_seconds"] is not None
    assert body["p50_seconds"] is not None
    assert body["p90_seconds"] is not None
    assert body["p99_seconds"] is not None
    assert sum(b["count"] for b in body["bins"]) == 3
    assert [b["label"] for b in body["bins"]] == [
        "0-1s",
        "1-2s",
        "2-5s",
        "5-10s",
        "10-30s",
        "30s+",
    ]
    assert {m["label"] for m in body["percentile_markers"]} == {"p50", "p90", "p99"}

    resp = client.get(
        "/api/analytics/jobs/duration", params={"plugin_id": "civex.get_field"}
    )
    assert resp.json()["count"] == 1

    resp = client.get("/api/analytics/jobs/duration", params={"status": "failed"})
    assert resp.json()["count"] == 2


def test_job_duration_stats_empty_is_all_nulls(client: TestClient) -> None:
    resp = client.get("/api/analytics/jobs/duration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["avg_seconds"] is None
    assert body["min_seconds"] is None
    assert body["max_seconds"] is None
    assert body["p50_seconds"] is None
    assert body["p90_seconds"] is None
    assert body["p99_seconds"] is None
    assert body["percentile_markers"] == []
    assert all(b["count"] == 0 for b in body["bins"])


def test_job_trigger_breakdown(client: TestClient) -> None:
    _setup_schema_and_collection(client)
    _run_workflows(client)

    resp = client.get("/api/analytics/jobs/by-trigger")
    assert resp.status_code == 200
    by_trigger = {item["trigger"]: item["count"] for item in resp.json()["items"]}
    # _run_workflows triggers every job manually.
    assert by_trigger == {"manual": 3}

    resp = client.get("/api/analytics/jobs/by-trigger", params={"status": "failed"})
    by_trigger = {item["trigger"]: item["count"] for item in resp.json()["items"]}
    assert by_trigger == {"manual": 2}


def test_audit_event_counts_by_action_and_entity_type(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "doc"})
    client.post("/api/collections", json={"name": "study"})
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": {}},
    )

    resp = client.get("/api/analytics/audit/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "day"
    by_entity = {item["entity_type"]: item["count"] for item in body["items"]}
    assert by_entity == {"schema": 1, "dataset": 1, "record": 1}
    assert {item["action"] for item in body["items"]} == {"create"}


def test_audit_event_counts_filters_by_entity_type_and_action(
    client: TestClient,
) -> None:
    client.post("/api/schemas", json={"name": "doc"})
    client.post("/api/collections", json={"name": "study"})
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": {}},
    )

    resp = client.get("/api/analytics/audit/events", params={"entity_type": "record"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {item["entity_type"] for item in items} == {"record"}
    assert sum(item["count"] for item in items) == 1

    resp = client.get("/api/analytics/audit/events", params={"action": "update"})
    assert resp.json()["items"] == []

    resp = client.get(
        "/api/analytics/audit/events",
        params={"entity_type": "dataset", "action": "create"},
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["entity_type"] == "dataset"
    assert items[0]["action"] == "create"


def test_ai_token_usage_by_provider_and_model(client: TestClient, ctx) -> None:
    ctx.ai_usage_svc.record("anthropic", "claude-sonnet-5", 100, 50)
    ctx.ai_usage_svc.record("anthropic", "claude-sonnet-5", 10, 5)
    ctx.ai_usage_svc.record("openai-compat", "llama-3", 7, 3)

    resp = client.get("/api/analytics/ai/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "day"
    by_model = {(i["provider"], i["model"]): i for i in body["items"]}
    assert by_model[("anthropic", "claude-sonnet-5")]["input_tokens"] == 110
    assert by_model[("anthropic", "claude-sonnet-5")]["output_tokens"] == 55
    assert by_model[("openai-compat", "llama-3")]["input_tokens"] == 7


def test_ai_token_usage_scoped_to_provider_and_model(client: TestClient, ctx) -> None:
    ctx.ai_usage_svc.record("anthropic", "claude-sonnet-5", 100, 50)
    ctx.ai_usage_svc.record("anthropic", "claude-haiku-4-5", 20, 10)
    ctx.ai_usage_svc.record("openai-compat", "llama-3", 7, 3)

    resp = client.get("/api/analytics/ai/usage", params={"provider": "anthropic"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["provider"] for i in items} == {"anthropic"}
    assert {i["model"] for i in items} == {"claude-sonnet-5", "claude-haiku-4-5"}

    resp = client.get(
        "/api/analytics/ai/usage",
        params={"provider": "anthropic", "model": "claude-sonnet-5"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["input_tokens"] == 100
    assert items[0]["output_tokens"] == 50
