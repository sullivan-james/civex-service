"""GET /records/search: one query across every schema and collection, for the
web UI's jump-to box."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _record(client: TestClient, collection: str, schema: str, **data) -> dict:
    resp = client.post(
        f"/api/collections/{collection}/records",
        json={"schema_name": schema, "data": data},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed(client: TestClient) -> dict[str, dict]:
    for schema in ("recording", "selection"):
        client.post("/api/schemas", json={"name": schema})
        client.post(
            f"/api/schemas/{schema}/fields", json={"name": "name", "type": "string"}
        )
    client.post("/api/collections", json={"name": "whales"})
    client.post("/api/collections", json={"name": "birds"})
    return {
        "whale_rec": _record(client, "whales", "recording", name="Humpback song"),
        "whale_sel": _record(client, "whales", "selection", name="Humpback unit 3"),
        "bird_rec": _record(client, "birds", "recording", name="Humpback-like call"),
        "other": _record(client, "birds", "selection", name="Wren"),
    }


def _search(client: TestClient, q: str, **params):
    return client.get("/api/records/search", params={"q": q, **params})


def test_searches_every_schema_and_collection_in_one_call(client: TestClient) -> None:
    recs = _seed(client)
    resp = _search(client, "humpback")
    assert resp.status_code == 200, resp.text
    found = {r["id"] for r in resp.json()}
    assert found == {
        recs["whale_rec"]["id"],
        recs["whale_sel"]["id"],
        recs["bird_rec"]["id"],
    }


def test_each_result_names_its_schema_and_collection(client: TestClient) -> None:
    recs = _seed(client)
    by_id = {r["id"]: r for r in _search(client, "humpback").json()}
    assert by_id[recs["whale_rec"]["id"]]["collection"] == "whales"
    assert by_id[recs["bird_rec"]["id"]]["collection"] == "birds"
    assert by_id[recs["whale_sel"]["id"]]["schema_name"] == "selection"
    assert by_id[recs["whale_rec"]["id"]]["natural_name"] == "Humpback song"


def test_collection_param_narrows_the_search(client: TestClient) -> None:
    recs = _seed(client)
    resp = _search(client, "humpback", collection="birds")
    assert [r["id"] for r in resp.json()] == [recs["bird_rec"]["id"]]


def test_unknown_collection_is_404(client: TestClient) -> None:
    _seed(client)
    assert _search(client, "humpback", collection="nope").status_code == 404


def test_a_record_id_prefix_finds_the_record(client: TestClient) -> None:
    recs = _seed(client)
    resp = _search(client, recs["other"]["id"][:8])
    assert [r["id"] for r in resp.json()] == [recs["other"]["id"]]


def test_limit_caps_results(client: TestClient) -> None:
    _seed(client)
    assert len(_search(client, "humpback", limit=2).json()) == 2


def test_deleted_records_are_not_returned(client: TestClient) -> None:
    recs = _seed(client)
    assert client.delete(f"/api/records/{recs['whale_rec']['id']}").status_code == 204
    found = {r["id"] for r in _search(client, "humpback").json()}
    assert recs["whale_rec"]["id"] not in found
    assert recs["whale_sel"]["id"] in found


def test_records_of_a_deleted_collection_are_not_returned(client: TestClient) -> None:
    recs = _seed(client)
    assert client.delete("/api/collections/birds").status_code in (200, 204)
    found = {r["id"] for r in _search(client, "humpback").json()}
    assert recs["bird_rec"]["id"] not in found
    assert recs["whale_rec"]["id"] in found


def test_like_wildcards_in_the_query_are_literal(client: TestClient) -> None:
    _seed(client)
    assert _search(client, "%").json() == []
    assert _search(client, "hump_ack").json() == []


def test_blank_or_missing_query_is_rejected_or_empty(client: TestClient) -> None:
    _seed(client)
    assert client.get("/api/records/search").status_code == 422
    assert _search(client, "").status_code == 422
    assert _search(client, "   ").json() == []


def test_search_is_not_shadowed_by_the_record_id_route(client: TestClient) -> None:
    _seed(client)
    # Would be a 404/422 from GET /records/{record_id} if routed there.
    assert _search(client, "wren").status_code == 200


def test_search_matches_values_not_keys_or_file_hashes(client: TestClient) -> None:
    """The jump-to box, the schema-wide list and a collection's list share the
    one rule: a value contains the text."""
    _seed(client)
    client.post("/api/schemas/recording/fields", json={"name": "audio", "type": "file"})
    upload = client.post("/api/files", files={"file": ("song.wav", b"bytes")})
    assert upload.status_code == 201, upload.text
    ref = upload.json()
    rec = _record(client, "whales", "recording", name="Blue whale", audio=ref)
    sha = ref["sha256"][:6]
    assert _search(client, sha).json() == []
    assert (
        client.get("/api/records", params={"schema": "recording", "search": sha}).json()
        == []
    )
    listed = client.get("/api/collections/whales/records", params={"search": sha})
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []
    assert [r["id"] for r in _search(client, "song.wav").json()] == [rec["id"]]


def test_search_field_narrows_the_search_to_one_field(client: TestClient) -> None:
    _seed(client)
    client.post(
        "/api/schemas/recording/fields", json={"name": "site", "type": "string"}
    )
    north = _record(client, "whales", "recording", name="Song", site="Humpback bay")
    params = {"schema": "recording", "search": "humpback"}
    everywhere = client.get("/api/collections/whales/records", params=params)
    assert north["id"] in {r["id"] for r in everywhere.json()["items"]}
    in_name = client.get(
        "/api/collections/whales/records", params={**params, "search_field": "name"}
    )
    assert north["id"] not in {r["id"] for r in in_name.json()["items"]}
    in_site = client.get(
        "/api/records", params={**params, "search_field": "site"}
    ).json()
    assert [r["id"] for r in in_site] == [north["id"]]
    bad = client.get(
        "/api/collections/whales/records", params={**params, "search_field": "nope"}
    )
    assert bad.status_code == 422
