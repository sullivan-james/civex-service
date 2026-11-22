"""Formula fields over HTTP: the preview endpoint, values in `derived` on
every record read, and the field type served to the editor."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _setup(client: TestClient) -> str:
    assert client.post("/api/schemas", json={"name": "patient"}).status_code == 201
    for name, dtype in (("mass", "float"), ("height", "float")):
        r = client.post(
            "/api/schemas/patient/fields", json={"name": name, "type": dtype}
        )
        assert r.status_code == 201, r.text
    r = client.post(
        "/api/schemas/patient/fields",
        json={
            "name": "bmi",
            "type": "formula",
            "restrictions": {"expression": "mass / height ** 2", "decimals": 1},
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["restrictions"]["result"] == "float"
    assert client.post("/api/collections", json={"name": "study"}).status_code == 201
    r = client.post(
        "/api/collections/study/records",
        json={
            "schema_name": "patient",
            "data": {"mass": 81.0, "height": 1.8, "bmi": 5},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_record_read_carries_its_formulas(client: TestClient) -> None:
    rid = _setup(client)
    got = client.get(f"/api/records/{rid}").json()
    assert got["derived"]["bmi"] == 25.0
    assert "bmi" not in got["data"]
    assert got["formula_errors"] is None
    listed = client.get("/api/collections/study/records?schema=patient").json()
    assert listed["items"][0]["derived"]["bmi"] == 25.0

    client.patch(f"/api/records/{rid}", json={"data": {"mass": 1.0, "height": 0}})
    got = client.get(f"/api/records/{rid}").json()
    assert got["derived"]["bmi"] is None
    assert "divided by zero" in got["formula_errors"]["bmi"]


def test_a_formula_cant_be_a_filter_or_sort(client: TestClient) -> None:
    _setup(client)
    r = client.get(
        "/api/collections/study/records",
        params={"schema": "patient", "sort": "bmi"},
    )
    assert r.status_code in (400, 422), r.text
    assert "sorted" in r.text


def test_preview_formula(client: TestClient) -> None:
    rid = _setup(client)
    r = client.post(
        "/api/schemas/patient/fields/preview-formula",
        json={"expression": "mass * 2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["value"] == 162.0 and body["result"] == "float"
    assert body["record_id"] == rid

    r = client.post(
        "/api/schemas/patient/fields/preview-formula",
        json={"expression": "mass + nope"},
    ).json()
    assert "nope" in r["problem"] and r["value"] is None

    r = client.post(
        "/api/schemas/patient/fields/preview-formula",
        json={"expression": "mass > 1", "values": {"mass": 3}},
    ).json()
    assert r["value"] is True and r["result"] == "boolean"

    r = client.post(
        "/api/schemas/nope/fields/preview-formula", json={"expression": "1"}
    )
    assert r.status_code == 404


def test_the_field_type_says_it_is_computed(client: TestClient) -> None:
    types = client.get("/api/schemas/field-types").json()
    formula = next(t for t in types["types"] if t["type"] == "formula")
    assert formula["computed"] is True
    assert formula["searchable"] is False and formula["measures"] == []
    assert [r["key"] for r in formula["restrictions"]] == [
        "expression",
        "result",
        "unit",
        "decimals",
    ]
    assert any(k["type"] == "formula" for k in types["kinds"])
