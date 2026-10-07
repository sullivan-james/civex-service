from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from civex.config import load_config


def _tomorrow() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def _setup(client: TestClient) -> list[str]:
    client.post("/api/schemas", json={"name": "trial"})
    client.post("/api/collections", json={"name": "study"})
    return [
        client.post(
            "/api/collections/study/records", json={"schema_name": "trial", "data": {}}
        ).json()["id"]
        for _ in range(3)
    ]


def test_settings_default_to_keeping_everything(client: TestClient) -> None:
    body = client.get("/api/settings/retention").json()
    assert body == {
        "purge_after_days": 30,
        "auto_purge_deleted": False,
        "audit_days": None,
        "run_days": None,
    }


def test_settings_are_saved_and_survive_a_reload(client: TestClient) -> None:
    saved = client.patch(
        "/api/settings/retention",
        json={"auto_purge_deleted": True, "audit_days": 365, "run_days": 30},
    ).json()
    assert saved["auto_purge_deleted"] is True
    assert (saved["audit_days"], saved["run_days"]) == (365, 30)
    assert saved["purge_after_days"] == 30  # not sent, not changed

    on_disk = load_config().retention
    assert (on_disk.auto_purge_deleted, on_disk.audit_days, on_disk.run_days) == (
        True,
        365,
        30,
    )
    assert client.get("/api/settings/retention").json()["audit_days"] == 365


def test_a_null_puts_a_kind_back_to_keep_forever(client: TestClient) -> None:
    client.patch("/api/settings/retention", json={"audit_days": 90, "run_days": 7})
    cleared = client.patch("/api/settings/retention", json={"audit_days": None}).json()
    assert cleared["audit_days"] is None and cleared["run_days"] == 7
    assert load_config().retention.audit_days is None


def test_settings_reject_a_nonsense_period(client: TestClient) -> None:
    assert (
        client.patch("/api/settings/retention", json={"audit_days": 0}).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/settings/retention", json={"purge_after_days": -1}
        ).status_code
        == 422
    )


def test_a_dry_run_counts_and_changes_nothing(client: TestClient) -> None:
    ids = _setup(client)
    client.post("/api/records/bulk-delete", json={"ids": ids})
    body = client.post(
        "/api/retention/run", json={"deleted_before": _tomorrow()}
    ).json()
    assert (body["dry_run"], body["deleted_records"]) == (True, 3)
    assert client.get(f"/api/records/{ids[0]}/restore-plan").status_code == 200


def test_a_run_by_date_removes_for_good_and_history_remembers(
    client: TestClient,
) -> None:
    ids = _setup(client)
    client.post("/api/records/bulk-delete", json={"ids": ids})
    done = client.post(
        "/api/retention/run", json={"dry_run": False, "deleted_before": _tomorrow()}
    ).json()
    assert done["deleted_records"] == 3
    assert client.get(f"/api/records/{ids[0]}/restore-plan").status_code == 404
    gone = client.get(
        "/api/audit/events",
        params={"filter": '{"field":"now","op":"eq","value":"gone"}'},
    ).json()
    assert gone["total"] >= 1


def test_applying_the_settings_only_touches_what_is_switched_on(
    client: TestClient,
) -> None:
    ids = _setup(client)
    # Two edits: the first is neither the schema's creation nor its latest
    # entry (both of which are kept however old), so it can be pruned.
    client.patch("/api/schemas/trial", json={"label": "Trial"})
    client.patch("/api/schemas/trial", json={"label": "Trials"})
    client.post("/api/records/bulk-delete", json={"ids": ids})
    # Nothing is switched on: applying the settings removes nothing.
    nothing = client.post(
        "/api/retention/run", json={"dry_run": False, "from_settings": True}
    ).json()
    assert nothing["anything"] is False
    # An explicit date wins even with the settings off.
    some = client.post("/api/retention/run", json={"audit_before": _tomorrow()}).json()
    assert some["audit_entries"] > 0 and some["deleted_records"] == 0


def test_purging_a_record_leaves_only_a_tombstone_in_history(
    client: TestClient,
) -> None:
    ids = _setup(client)
    client.delete(f"/api/records/{ids[0]}")
    client.delete(f"/api/records/{ids[0]}/purge")
    history = client.get(f"/api/audit?entity_id={ids[0]}").json()["items"]
    assert [(e["action"], e["new_data"]) for e in history] == [("purge", None)]
    assert history[0]["old_data"]["tombstone"] is True
    assert "data" not in history[0]["old_data"]
    # Nothing left to clean up: purging already did it.
    body = client.post("/api/retention/purged-history", json={}).json()
    assert (body["dry_run"], body["entries"]) == (True, 0)
    done = client.post("/api/retention/purged-history", json={"dry_run": False}).json()
    assert done["entries"] == 0
