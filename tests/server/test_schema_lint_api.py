"""HTTP contract for GET /api/schemas/lint -- the naming-lint report
`civex schema lint` prints, exposed for the analytics naming-health widget."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_lint_reports_nothing_for_a_clean_project(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "trial"})
    resp = client.get("/api/schemas/lint")
    assert resp.status_code == 200
    assert resp.json() == []


def test_lint_reports_legacy_names_with_suggestions(client: TestClient, ctx) -> None:
    ctx.schema_svc.create("Legacy Schema", allow_legacy_name=True)
    ctx.schema_svc.add_field(
        "Legacy Schema", "Legacy Field", "string", allow_legacy_name=True
    )
    ctx.schema_svc.add_field("Legacy Schema", "fine_field", "string")
    ctx.commit()

    resp = client.get("/api/schemas/lint")
    assert resp.status_code == 200
    issues = {(i["kind"], i["name"], i["suggestion"]) for i in resp.json()}
    assert issues == {
        ("schema", "Legacy Schema", "legacy_schema"),
        ("field", "Legacy Field", "legacy_field"),
    }
