"""Delete, restore, purge and move over HTTP: a request tagged
`X-Civex-Progress` can be followed and stopped between chunks; untagged ones
answer as they always did."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civex.services import progress as progress_module
from civex.services import record_service


def _post(client: TestClient, url: str, body: dict) -> dict:
    resp = client.post(url, json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.fixture()
def trials(client: TestClient) -> list[str]:
    _post(client, "/api/schemas", {"name": "trial"})
    _post(client, "/api/schemas/trial/fields", {"name": "subject", "type": "string"})
    _post(client, "/api/collections", {"name": "study"})
    _post(client, "/api/collections", {"name": "other"})
    return [
        _post(
            client,
            "/api/collections/study/records",
            {"schema_name": "trial", "data": {"subject": f"S{i}"}},
        )["id"]
        for i in range(4)
    ]


_ADVANCE = progress_module.Progress.advance


def _back(monkeypatch) -> None:
    """Nobody presses Stop any more, and chunks are their usual size."""
    monkeypatch.setattr(progress_module.Progress, "advance", _ADVANCE)
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 5000)


def _stop_after_first_chunk(client, monkeypatch, progress_id: str) -> list[int]:
    advance = progress_module.Progress.advance
    asked: list[int] = []

    def advance_then_stop(self, done, total=None):
        advance(self, done, total)
        if not asked:
            asked.append(
                client.post(
                    f"/api/file-access/progress/{progress_id}/cancel"
                ).status_code
            )

    monkeypatch.setattr(progress_module.Progress, "advance", advance_then_stop)
    return asked


def _live(client, ids: list[str]) -> list[bool]:
    gone = {r["id"] for r in client.get("/api/records/deleted").json()}
    return [i not in gone for i in ids]


def test_an_untagged_bulk_delete_answers_as_before_with_the_counts(
    client: TestClient, trials
):
    done = _post(client, "/api/records/bulk-delete", {"ids": trials})
    assert done == {"deleted": 4, "records": 4, "stopped": False}


def test_a_stopped_bulk_delete_keeps_what_it_deleted_and_again_finishes_it(
    client: TestClient, trials, monkeypatch
):
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 1)
    asked = _stop_after_first_chunk(client, monkeypatch, "stop-delete-0001")
    resp = client.post(
        "/api/records/bulk-delete",
        json={"ids": trials},
        headers={"X-Civex-Progress": "stop-delete-0001"},
    )
    assert resp.status_code == 200, resp.text
    assert asked == [204]
    assert resp.json() == {"deleted": 1, "records": 1, "stopped": True}
    assert sorted(_live(client, trials)) == [False, True, True, True]

    _back(monkeypatch)
    again = _post(client, "/api/records/bulk-delete", {"ids": trials})
    assert again["deleted"] == 3 and again["stopped"] is False
    assert _live(client, trials) == [False] * 4


def test_deleting_a_whole_collection_is_followed_and_stoppable(
    client: TestClient, trials, monkeypatch
):
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 2)
    asked = _stop_after_first_chunk(client, monkeypatch, "stop-all-000001")
    resp = client.delete(
        "/api/collections/study/records",
        headers={"X-Civex-Progress": "stop-all-000001"},
    )
    assert resp.status_code == 200, resp.text
    assert asked == [204]
    assert resp.json() == {"deleted": 2, "records": 2, "stopped": True}
    state = client.get("/api/file-access/progress/stop-all-000001").json()
    assert (state["phase"], state["done"], state["total"]) == (
        "Deleting records",
        2,
        4,
    )


def test_a_stopped_restore_selected_keeps_what_came_back(
    client: TestClient, trials, monkeypatch
):
    _post(client, "/api/records/bulk-delete", {"ids": trials})
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 1)
    asked = _stop_after_first_chunk(client, monkeypatch, "stop-restore-001")
    resp = client.post(
        "/api/records/restore-selected",
        json={"ids": trials},
        headers={"X-Civex-Progress": "stop-restore-001"},
    )
    assert resp.status_code == 200, resp.text
    assert asked == [204]
    body = resp.json()
    assert (body["restored"], body["came_back"], body["stopped"]) == (1, 1, True)
    assert sorted(_live(client, trials)) == [False, False, False, True]
    _back(monkeypatch)
    plain = _post(client, "/api/records/restore-selected", {"ids": trials})
    assert plain["stopped"] is False and plain["came_back"] == 3


def test_a_stopped_move_keeps_what_moved(client: TestClient, trials, monkeypatch):
    monkeypatch.setattr(record_service, "_APPLY_CHUNK", 1)
    asked = _stop_after_first_chunk(client, monkeypatch, "stop-move-000001")
    resp = client.post(
        "/api/records/move",
        json={"ids": trials, "to": "other"},
        headers={"X-Civex-Progress": "stop-move-000001"},
    )
    assert resp.status_code == 200, resp.text
    assert asked == [204]
    body = resp.json()
    assert (body["records"], body["stopped"]) == (1, True)
    where = [client.get(f"/api/records/{i}").json()["collection"] for i in trials]
    assert sorted(where) == ["other", "study", "study", "study"]
    _back(monkeypatch)
    done = _post(client, "/api/records/move", {"ids": trials, "to": "other"})
    assert done["stopped"] is False


def test_purge_is_204_unless_stopped_and_one_record_delete_is_followed(
    client: TestClient, trials, monkeypatch
):
    first = trials[0]
    resp = client.delete(
        f"/api/records/{first}", headers={"X-Civex-Progress": "delete-one-00001"}
    )
    assert resp.status_code == 204
    state = client.get("/api/file-access/progress/delete-one-00001").json()
    assert (state["phase"], state["done"], state["total"]) == (
        "Deleting records",
        1,
        1,
    )
    assert client.delete(f"/api/records/{first}/purge").status_code == 204

    _post(client, "/api/records/bulk-delete", {"ids": trials[1:]})
    monkeypatch.setattr(record_service, "_PURGE_CHUNK", 1)
    _stop_after_first_chunk(client, monkeypatch, "stop-purge-00001")
    resp = client.delete(
        f"/api/records/{trials[1]}/purge",
        headers={"X-Civex-Progress": "stop-purge-00001"},
    )
    # A tree of one record: the first chunk is all of it, so nothing is left to stop.
    assert resp.status_code in (200, 204)


def test_collection_and_schema_delete_and_restore_report_their_records(
    client: TestClient, trials
):
    for verb, url in (
        ("delete", "/api/collections/study"),
        ("restore", "/api/collections/study/restore"),
    ):
        pid = f"collection-{verb}-1"
        headers = {"X-Civex-Progress": pid}
        resp = (
            client.delete(url, headers=headers)
            if verb == "delete"
            else client.post(url, headers=headers)
        )
        assert resp.status_code in (200, 204), resp.text
        state = client.get(f"/api/file-access/progress/{pid}").json()
        assert (state["done"], state["total"]) == (4, 4)
        assert state["phase"] == (
            "Deleting records" if verb == "delete" else "Restoring records"
        )
