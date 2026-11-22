"""POST /records/bulk-edit and its plan: fields set on many records at once,
by id or by the same query a list shows."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _post(client: TestClient, url: str, body: dict) -> dict:
    resp = client.post(url, json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _setup(client: TestClient) -> list[dict]:
    _post(client, "/api/schemas", {"name": "trial"})
    _post(client, "/api/schemas/trial/fields", {"name": "subject", "type": "string"})
    _post(
        client,
        "/api/schemas/trial/fields",
        {"name": "dose", "type": "integer", "restrictions": {"max": 10}},
    )
    _post(client, "/api/collections", {"name": "study"})
    return [
        _post(
            client,
            "/api/collections/study/records",
            {"schema_name": "trial", "data": {"subject": f"S{i}"}},
        )
        for i in range(3)
    ]


def test_the_plan_says_what_would_change_and_the_edit_does_it(client: TestClient):
    trials = _setup(client)
    ids = [t["id"] for t in trials]

    plan = _post(
        client, "/api/records/bulk-edit/plan", {"ids": ids, "changes": {"dose": 5}}
    )
    assert plan["can_apply"] is True
    assert (plan["records"], plan["changing"], plan["skipped"]) == (3, 3, 0)

    done = _post(client, "/api/records/bulk-edit", {"ids": ids, "changes": {"dose": 5}})
    assert (done["changed"], done["unchanged"], done["skipped"]) == (3, 0, 0)
    for t in trials:
        assert client.get(f"/api/records/{t['id']}").json()["data"]["dose"] == 5

    cleared = _post(
        client, "/api/records/bulk-edit", {"ids": ids[:1], "changes": {"dose": None}}
    )
    assert cleared["changed"] == 1
    got = client.get(f"/api/records/{ids[0]}").json()["data"]
    assert got.get("dose") is None


def test_a_query_edits_what_the_list_shows_and_bad_values_are_named(
    client: TestClient,
):
    _setup(client)
    body = {
        "collection": "study",
        "schema_name": "trial",
        "search": "S1",
        "changes": {"dose": 99},
    }
    plan = _post(client, "/api/records/bulk-edit/plan", body)
    assert (plan["records"], plan["skipped"], plan["can_apply"]) == (1, 1, False)
    assert plan["skipped_records"][0]["name"] == "S1"
    assert "dose" in plan["skipped_records"][0]["reason"]


def test_no_records_or_no_changes_is_a_422(client: TestClient):
    _setup(client)
    resp = client.post("/api/records/bulk-edit/plan", json={"changes": {"dose": 1}})
    assert resp.status_code == 422
    resp = client.post(
        "/api/records/bulk-edit", json={"collection": "study", "changes": {}}
    )
    assert resp.status_code == 422


def test_a_bulk_edit_is_undone_from_its_line_in_history(client: TestClient):
    trials = _setup(client)
    ids = [t["id"] for t in trials]
    _post(client, "/api/records/bulk-edit", {"ids": ids, "changes": {"dose": 5}})
    events = client.get("/api/audit/events", params={"limit": 1}).json()["items"]
    batch = events[0]["batch"]
    assert batch["kind"] == "edit"

    plan = client.get(f"/api/audit/batches/{batch['id']}/revert").json()
    assert (plan["entries"], plan["applied"], plan["left"]) == (3, 3, 0)

    done = _post(client, f"/api/audit/batches/{batch['id']}/revert", {})
    assert done["applied"] == 3
    for record_id in ids:
        data = client.get(f"/api/records/{record_id}").json()["data"]
        assert data.get("dose") is None


def test_a_stopped_edit_keeps_what_it_changed_and_the_same_request_finishes_it(
    client: TestClient, monkeypatch
):
    """Asked to stop (`POST /file-access/progress/{id}/cancel`), it stops
    before its next chunk, says so, and leaves whole records; sending the
    same edit again changes the rest."""
    from civex.services import progress as progress_module
    from civex.services import record_service

    trials = _setup(client)
    ids = [t["id"] for t in trials]
    progress_id = "stop-this-edit-1"
    monkeypatch.setattr(record_service, "BULK_EDIT_PAGE", 1)
    advance = progress_module.Progress.advance
    asked: list[int] = []

    def advance_then_stop(self, done, total=None):
        advance(self, done, total)
        if not asked:  # after its first chunk, someone presses Stop
            asked.append(
                client.post(
                    f"/api/file-access/progress/{progress_id}/cancel"
                ).status_code
            )

    monkeypatch.setattr(progress_module.Progress, "advance", advance_then_stop)
    body = {"ids": ids, "changes": {"dose": 5}}

    resp = client.post(
        "/api/records/bulk-edit", json=body, headers={"X-Civex-Progress": progress_id}
    )

    assert resp.status_code == 200, resp.text
    stopped = resp.json()
    assert asked == [204]
    assert (stopped["stopped"], stopped["changed"]) == (True, 1)
    doses = [client.get(f"/api/records/{i}").json()["data"].get("dose") for i in ids]
    assert sorted(doses, key=str) == [5, None, None]

    monkeypatch.setattr(progress_module.Progress, "advance", advance)
    again = _post(client, "/api/records/bulk-edit", body)
    assert (again["stopped"], again["changed"], again["unchanged"]) == (False, 2, 1)
    # Nothing is reporting under an id that isn't in use.
    assert (
        client.post("/api/file-access/progress/nothing-here-0/cancel").status_code
        == 404
    )
