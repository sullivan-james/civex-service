"""POST /records/delete-preview: what a delete takes, and the confirmation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civex.domain.delete_policy import TYPED_CONFIRM_ABOVE


def _post(client: TestClient, url: str, body: dict) -> dict:
    resp = client.post(url, json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _setup(client: TestClient) -> None:
    _post(client, "/api/schemas", {"name": "site"})
    _post(client, "/api/schemas/site/fields", {"name": "name", "type": "string"})
    _post(client, "/api/schemas", {"name": "visit", "parent": "site"})
    _post(client, "/api/collections", {"name": "survey"})


def _site(client: TestClient, name: str, visits: int = 0) -> dict:
    site = _post(
        client,
        "/api/collections/survey/records",
        {"schema_name": "site", "data": {"name": name}},
    )
    for _ in range(visits):
        _post(
            client,
            "/api/collections/survey/records",
            {"schema_name": "visit", "data": {}, "parent_record_id": site["id"]},
        )
    return site


def test_a_few_records_are_a_plain_confirm(client: TestClient):
    _setup(client)
    ids = [_site(client, str(i))["id"] for i in range(3)]
    got = _post(client, "/api/records/delete-preview", {"ids": ids})
    assert got == {"chosen": 3, "records": 3, "cascading": 0, "confirm": "plain"}


def test_what_sits_beneath_counts_towards_a_large_delete(client: TestClient):
    _setup(client)
    one = _site(client, "a", visits=TYPED_CONFIRM_ABOVE)
    got = _post(client, "/api/records/delete-preview", {"ids": [one["id"]]})
    assert got["chosen"] == 1
    assert got["cascading"] == TYPED_CONFIRM_ABOVE
    assert got["records"] == TYPED_CONFIRM_ABOVE + 1
    assert got["confirm"] == "type"


def test_a_small_cascade_stays_plain_and_a_query_is_previewed_like_a_list(
    client: TestClient,
):
    _setup(client)
    _site(client, "a", visits=2)
    _site(client, "b")
    got = _post(
        client,
        "/api/records/delete-preview",
        {"collection": "survey", "schema_name": "site"},
    )
    assert (got["chosen"], got["records"], got["cascading"]) == (2, 4, 2)
    assert got["confirm"] == "plain"


def test_nothing_chosen_is_refused(client: TestClient):
    resp = client.post("/api/records/delete-preview", json={})
    assert resp.status_code == 422
