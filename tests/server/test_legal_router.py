"""HTTP-level tests for /api/legal. New coverage -- no prior surface existed
for this.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_get_license_returns_the_project_license_text(client: TestClient) -> None:
    resp = client.get("/api/legal/license")
    assert resp.status_code == 200
    assert "PolyForm Shield License" in resp.json()["text"]


def test_list_policies_empty(client: TestClient) -> None:
    resp = client.get("/api/legal/policies")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_and_get_a_policy(client: TestClient, project_dir: Path) -> None:
    policies_dir = project_dir / "_civex" / "policies"
    policies_dir.mkdir(parents=True)
    (policies_dir / "data-handling.md").write_text(
        "# Data Handling Policy\n\nDe-identify before export.\n"
    )

    list_resp = client.get("/api/legal/policies")
    assert list_resp.status_code == 200
    assert list_resp.json() == [
        {
            "stem": "data-handling",
            "title": "Data Handling Policy",
            "content": "# Data Handling Policy\n\nDe-identify before export.\n",
        }
    ]

    get_resp = client.get("/api/legal/policies/data-handling")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Data Handling Policy"


def test_get_unknown_policy_is_404(client: TestClient) -> None:
    resp = client.get("/api/legal/policies/nope")
    assert resp.status_code == 404
