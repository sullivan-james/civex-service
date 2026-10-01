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


def test_map_settings_default_to_bundled_coastlines(client: TestClient) -> None:
    resp = client.get("/api/settings/map")
    assert resp.status_code == 200
    assert resp.json() == {"tile_url": None, "attribution": None}


def test_map_settings_round_trip_with_quotes_in_the_credit(client: TestClient) -> None:
    body = {
        "tile_url": "https://tile.example.org/{z}/{x}/{y}.png",
        "attribution": 'Tiles by "Example" & contributors',
    }
    assert client.patch("/api/settings/map", json=body).json() == body
    assert client.get("/api/settings/map").json() == body
    # clearing the URL clears the credit with it
    cleared = client.patch("/api/settings/map", json={"tile_url": None}).json()
    assert cleared == {"tile_url": None, "attribution": None}


def test_map_settings_reject_a_url_that_is_not_a_tile_template(client: TestClient) -> None:
    for bad in ("tile.example.org/{z}/{x}/{y}", "https://tile.example.org/map.png", "ftp://x/{z}/{x}/{y}"):
        resp = client.patch("/api/settings/map", json={"tile_url": bad})
        assert resp.status_code == 422, bad
