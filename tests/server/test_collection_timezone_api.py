"""Collection timezones: how offset-less datetimes are read on the API write
path, and the collection create/update contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

CHICAGO = "America/Chicago"


def _setup(
    client: TestClient, tz: str | None, field_restrictions: dict | None = None
) -> None:
    body: dict = {"name": "study"}
    if tz is not None:
        body["timezone"] = tz
    assert client.post("/api/collections", json=body).status_code == 201
    assert client.post("/api/schemas", json={"name": "sample"}).status_code == 201
    r = client.post(
        "/api/schemas/sample/fields",
        json={
            "name": "taken_at",
            "type": "datetime",
            "restrictions": field_restrictions or {},
        },
    )
    assert r.status_code == 201, r.text


def _add(client: TestClient, value: str):
    return client.post(
        "/api/collections/study/records",
        json={"schema_name": "sample", "data": {"taken_at": value}},
    )


def test_collection_timezone_roundtrips_and_clears(client: TestClient) -> None:
    created = client.post(
        "/api/collections", json={"name": "study", "timezone": CHICAGO}
    )
    assert created.status_code == 201
    assert created.json()["timezone"] == CHICAGO
    assert client.get("/api/collections/study").json()["timezone"] == CHICAGO

    cleared = client.patch("/api/collections/study", json={"timezone": ""})
    assert cleared.status_code == 200
    assert cleared.json()["timezone"] is None


def test_unrelated_update_leaves_timezone_alone(client: TestClient) -> None:
    client.post("/api/collections", json={"name": "study", "timezone": CHICAGO})
    r = client.patch("/api/collections/study", json={"description": "x"})
    assert r.json()["timezone"] == CHICAGO


def test_invalid_timezone_is_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/collections", json={"name": "study", "timezone": "Mars/Olympus"}
    )
    assert r.status_code == 422
    assert "Unknown timezone" in r.json()["detail"]
    client.post("/api/collections", json={"name": "other"})
    r = client.patch("/api/collections/other", json={"timezone": "nope"})
    assert r.status_code == 422


def test_naive_datetime_is_read_in_the_collection_zone(client: TestClient) -> None:
    _setup(client, CHICAGO)
    r = _add(client, "2024-03-01T15:30")  # CST, UTC-6
    assert r.status_code == 201, r.text
    assert r.json()["data"]["taken_at"] == "2024-03-01T21:30:00+00:00"


def test_naive_datetime_without_a_zone_is_read_as_utc(client: TestClient) -> None:
    """Previously the API stored this string as-is; now it's normalised."""
    _setup(client, None)
    r = _add(client, "2024-03-01T15:30")
    assert r.json()["data"]["taken_at"] == "2024-03-01T15:30:00+00:00"


def test_explicit_offset_wins_over_the_collection_zone(client: TestClient) -> None:
    _setup(client, CHICAGO)
    r = _add(client, "2024-03-01T15:30:00+00:00")
    assert r.json()["data"]["taken_at"] == "2024-03-01T15:30:00+00:00"


def test_field_timezone_overrides_the_collection_zone(client: TestClient) -> None:
    _setup(client, CHICAGO, {"timezone": "Asia/Kolkata"})
    r = _add(client, "2024-03-01T12:00")  # IST, UTC+5:30
    assert r.json()["data"]["taken_at"] == "2024-03-01T06:30:00+00:00"


def test_dst_gap_and_overlap_are_rejected(client: TestClient) -> None:
    _setup(client, CHICAGO)
    gap = _add(client, "2024-03-10T02:30")
    assert gap.status_code == 422
    assert "does not exist" in gap.json()["detail"]
    overlap = _add(client, "2024-11-03T01:30")
    assert overlap.status_code == 422
    assert "ambiguous" in overlap.json()["detail"]


def test_malformed_datetime_is_rejected(client: TestClient) -> None:
    _setup(client, CHICAGO)
    r = _add(client, "not a date")
    assert r.status_code == 422
    assert "taken_at" in r.json()["detail"]


def test_update_reads_changed_values_in_the_zone(client: TestClient) -> None:
    _setup(client, CHICAGO)
    rid = _add(client, "2024-03-01T15:30").json()["id"]
    r = client.patch(
        f"/api/records/{rid}", json={"data": {"taken_at": "2024-07-01T15:30"}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["taken_at"] == "2024-07-01T20:30:00+00:00"  # CDT


def test_update_does_not_shift_a_value_it_was_only_sent_back(
    client: TestClient,
) -> None:
    """The UI re-sends the whole record on every edit. A legacy offset-less
    value stored before the zone was set must not be re-read in that zone."""
    _setup(client, None)
    # Simulate a legacy row: stored offset-less, bypassing normalisation.
    rid = _add(client, "2024-03-01T15:30").json()["id"]
    from civex.config import load_config
    from civex.context import build_local_context

    ctx = build_local_context(load_config())
    try:
        record = ctx.record_svc._records.get_by_prefix(rid)
        assert record is not None
        field_id = next(iter(record.data))
        ctx.record_svc._records.update(record.id, {field_id: "2024-03-01T15:30:00"})
        ctx.commit()
    finally:
        ctx.close()

    assert (
        client.patch("/api/collections/study", json={"timezone": CHICAGO}).status_code
        == 200
    )
    r = client.patch(
        f"/api/records/{rid}", json={"data": {"taken_at": "2024-03-01T15:30:00"}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["taken_at"] == "2024-03-01T15:30:00"  # untouched


def test_field_timezone_restriction_is_validated(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "sample"})
    bad = client.post(
        "/api/schemas/sample/fields",
        json={
            "name": "t",
            "type": "datetime",
            "restrictions": {"timezone": "Mars/Olympus"},
        },
    )
    assert bad.status_code == 422
    padded = client.post(
        "/api/schemas/sample/fields",
        json={"name": "t", "type": "datetime", "restrictions": {"timezone": " UTC"}},
    )
    assert padded.status_code == 422
    not_datetime = client.post(
        "/api/schemas/sample/fields",
        json={"name": "s", "type": "string", "restrictions": {"timezone": "UTC"}},
    )
    assert not_datetime.status_code == 422
    ok = client.post(
        "/api/schemas/sample/fields",
        json={"name": "t", "type": "datetime", "restrictions": {"timezone": "UTC"}},
    )
    assert ok.status_code == 201
