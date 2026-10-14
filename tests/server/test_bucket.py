"""`/api/store/bucket`: where a project's files are kept, from the app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civex.domain import features as f
from civex.testing.fake_s3 import FakeS3


@pytest.fixture()
def s3(monkeypatch: pytest.MonkeyPatch) -> FakeS3:
    fake = FakeS3()
    monkeypatch.setattr(
        "civex.repositories.s3.store.boto_client", lambda _settings: fake
    )
    return fake


def test_an_empty_project_moves_to_a_bucket_and_back(client: TestClient, s3: FakeS3):
    assert client.get("/api/store/bucket").json()["bucket"] is None

    checked = client.post("/api/store/bucket/check", json={"bucket": "lab"})
    assert checked.json() == {"ok": True, "problems": [], "warnings": []}

    used = client.put("/api/store/bucket", json={"bucket": "lab", "prefix": "p"})
    assert used.status_code == 200, used.text
    assert used.json()["bucket"] == "lab"
    features = set(client.get("/api/status/features").json()["features"])
    assert f.VOLUMES not in features and f.DIRECT_FILES in features
    assert f.STORE_ADMIN in features

    back = client.delete("/api/store/bucket")
    assert back.json()["bucket"] is None
    assert f.VOLUMES in client.get("/api/status/features").json()["features"]


def test_a_project_with_files_on_drives_is_refused(client: TestClient, s3: FakeS3):
    added = client.put(
        "/api/files/stream",
        content=b"hello",
        headers={"X-Filename": "a.txt", "Content-Length": "5"},
    )
    assert added.status_code < 300, added.text
    status = client.get("/api/store/bucket").json()
    assert status["drive_files"] == 1 and not status["can_switch"]

    refused = client.put("/api/store/bucket", json={"bucket": "lab"})
    assert refused.status_code == 422
    assert "on its drives" in refused.json()["detail"]
    assert client.get("/api/store/bucket").json()["bucket"] is None


def test_a_bucket_that_fails_its_check_is_not_saved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    def unreachable(_settings: object) -> object:
        raise RuntimeError("no such host")

    monkeypatch.setattr("civex.repositories.s3.store.boto_client", unreachable)
    refused = client.put("/api/store/bucket", json={"bucket": "lab"})
    assert refused.status_code == 422
    assert "no such host" in refused.json()["detail"]
    assert client.get("/api/store/bucket").json()["bucket"] is None
