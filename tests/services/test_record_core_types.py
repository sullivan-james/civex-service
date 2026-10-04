"""End to end through RecordService: `geo` fields, partial dates and units."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import CoercionError, ValidationError


@pytest.fixture()
def deployment(ctx: AppContext, make_schema, make_collection):
    make_schema("deployment")
    make_collection("study")
    sv = ctx.schema_svc
    sv.add_field(
        "deployment",
        "deployed",
        "date",
        restrictions={"precision": "month", "min": "2020"},
    )
    sv.add_field(
        "deployment",
        "depth",
        "float",
        restrictions={"unit": "m", "min": 0, "max": 2000},
    )
    sv.add_field(
        "deployment",
        "release_point",
        "geo",
        restrictions={"geometry_types": ["Point"], "bbox": [-12, 48, 4, 62]},
    )
    return ctx


def test_partial_date_round_trips_unpadded(deployment: AppContext) -> None:
    rec = deployment.record_svc.add("study", "deployment", {"deployed": "2026-04"})
    deployment.commit()
    assert deployment.record_svc.get(str(rec.id)).data["deployed"] == "2026-04"


def test_date_coarser_than_precision_is_rejected(deployment: AppContext) -> None:
    with pytest.raises(ValidationError, match="at least month"):
        deployment.record_svc.add("study", "deployment", {"deployed": "2026"})


def test_geo_value_is_stored_as_geojson(deployment: AppContext) -> None:
    point = {"type": "Point", "coordinates": [-3.41, 56.12]}
    rec = deployment.record_svc.add("study", "deployment", {"release_point": point})
    deployment.commit()
    assert deployment.record_svc.get(str(rec.id)).data["release_point"] == point


def test_geo_outside_bbox_is_rejected(deployment: AppContext) -> None:
    far = {"type": "Point", "coordinates": [-20.1, 63.4]}
    with pytest.raises(ValidationError, match="outside the allowed area"):
        deployment.record_svc.add("study", "deployment", {"release_point": far})


def test_coerce_geo_from_text(deployment: AppContext) -> None:
    value = deployment.record_svc.coerce_value(
        "56.12, -3.41", "geo", "release_point", {"geometry_types": ["Point"]}
    )
    assert value == {"type": "Point", "coordinates": [-3.41, 56.12]}
    with pytest.raises(CoercionError):
        deployment.record_svc.coerce_value(
            "near the harbour", "geo", "release_point", {}
        )


def test_coerce_converts_into_the_fields_unit(deployment: AppContext) -> None:
    r = {"unit": "m", "min": 0, "max": 2000}
    coerce = deployment.record_svc.coerce_value
    assert coerce("312.4", "float", "depth", r) == 312.4
    assert coerce("1024 ft", "float", "depth", r) == pytest.approx(312.1152)
    assert coerce("312.4 m", "float", "depth", r) == 312.4
    with pytest.raises(ValidationError, match="exceeds maximum"):
        coerce("9000 ft", "float", "depth", r)
    with pytest.raises(ValidationError, match="time.*length"):
        coerce("5 s", "float", "depth", r)


def test_unitless_float_is_unchanged(deployment: AppContext) -> None:
    coerce = deployment.record_svc.coerce_value
    assert coerce("2.5", "float", "x", {}) == 2.5
    with pytest.raises(CoercionError):
        coerce("2.5 m", "float", "x", {})
