"""HTTP-level tests for /api/settings — the per-project UI preferences
introduced to gate the Advanced nav section (terminal, YAML editing, plugin
editors) behind an opt-in toggle, off by default for new projects.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_ui_settings_default_off(client: TestClient) -> None:
    resp = client.get("/api/settings/ui")
    assert resp.status_code == 200
    assert resp.json() == {"show_advanced": False}


def test_ui_settings_round_trips_through_patch(client: TestClient) -> None:
    patch_resp = client.patch("/api/settings/ui", json={"show_advanced": True})
    assert patch_resp.status_code == 200
    assert patch_resp.json() == {"show_advanced": True}

    get_resp = client.get("/api/settings/ui")
    assert get_resp.status_code == 200
    assert get_resp.json() == {"show_advanced": True}
