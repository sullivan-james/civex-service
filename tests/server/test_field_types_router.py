"""GET /schemas/field-types: the descriptors the web UI builds its editors from."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civex.domain.field_descriptors import FIELD_KINDS, FIELD_TYPES
from civex.services.schema_service import VALID_DTYPES, VALID_RESTRICTION_KEYS


def test_every_field_type_is_described() -> None:
    assert set(FIELD_TYPES) == set(VALID_DTYPES)


def test_save_time_keys_come_from_the_descriptors() -> None:
    for t, d in FIELD_TYPES.items():
        assert VALID_RESTRICTION_KEYS[t] == {r.key for r in d.restrictions}


def test_every_kind_creates_a_real_type_and_focuses_a_real_rule() -> None:
    for k in FIELD_KINDS:
        assert k.type in FIELD_TYPES
        if k.focus:
            assert k.focus in {r.key for r in FIELD_TYPES[k.type].restrictions}


def test_endpoint_serves_types_and_kinds(client: TestClient) -> None:
    body = client.get("/api/schemas/field-types").json()
    types = {t["type"]: t for t in body["types"]}
    assert set(types) == set(VALID_DTYPES)
    geo = types["geo"]
    assert [r["key"] for r in geo["restrictions"]] == ["geometry_types", "bbox"]
    assert "latitude" in geo["entry_hint"].lower()
    assert {"key": "unit", "control": "unit"}.items() <= {
        k: v
        for r in types["float"]["restrictions"]
        if r["key"] == "unit"
        for k, v in r.items()
    }.items()
    assert [k["key"] for k in body["kinds"]][:2] == ["text", "choice"]


def test_endpoint_is_not_shadowed_by_the_schema_name_route(client: TestClient) -> None:
    # "/schemas/{name_or_id}" would answer 404 for an unknown schema.
    assert client.get("/api/schemas/field-types").status_code == 200
