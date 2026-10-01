from __future__ import annotations

import pytest

from civex.domain import geo
from civex.domain.exceptions import ValidationError

POINT = {"type": "Point", "coordinates": [-3.41, 56.12]}
SQUARE = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
}


def test_valid_shapes_return_their_positions() -> None:
    assert geo.positions(POINT) == [(-3.41, 56.12)]
    assert len(geo.positions(SQUARE)) == 5
    assert len(geo.positions({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})) == 2


def test_altitude_is_allowed() -> None:
    assert geo.positions({"type": "Point", "coordinates": [1, 2, -300]}) == [(1.0, 2.0)]


@pytest.mark.parametrize(
    "bad",
    [
        "Point(1 2)",
        {"type": "Point"},
        {"type": "Point", "coordinates": [1]},
        {"type": "Point", "coordinates": ["1", "2"]},
        {"type": "Point", "coordinates": [True, 2]},
        {"type": "Point", "coordinates": [181, 0]},
        {"type": "Point", "coordinates": [0, 91]},
        {"type": "LineString", "coordinates": [[0, 0]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 5]]]},
        {"type": "Circle", "coordinates": [0, 0]},
    ],
)
def test_malformed_geometry_is_rejected(bad) -> None:
    with pytest.raises(ValidationError):
        geo.positions(bad)


def test_geometry_types_restriction() -> None:
    geo.check(POINT, {"geometry_types": ["Point"]})
    with pytest.raises(ValidationError, match="not allowed"):
        geo.check(SQUARE, {"geometry_types": ["Point"]})


def test_bbox_restriction() -> None:
    box = {"bbox": [-12, 48, 4, 62]}
    geo.check(POINT, box)
    with pytest.raises(ValidationError, match="outside the allowed area"):
        geo.check({"type": "Point", "coordinates": [-20.1, 63.4]}, box)


def test_bbox_across_the_antimeridian() -> None:
    box = {"bbox": [170, -20, -170, 20]}  # west > east
    geo.check({"type": "Point", "coordinates": [179, 0]}, box)
    geo.check({"type": "Point", "coordinates": [-175, 0]}, box)
    with pytest.raises(ValidationError):
        geo.check({"type": "Point", "coordinates": [0, 0]}, box)


def test_every_position_of_a_shape_must_be_inside() -> None:
    line = {"type": "LineString", "coordinates": [[0, 0], [50, 0]]}
    with pytest.raises(ValidationError):
        geo.check(line, {"bbox": [-1, -1, 10, 1]})


@pytest.mark.parametrize("bad", [[1, 2, 3], "x", [0, 10, 5, 5], [0, -91, 1, 1], [-181, 0, 1, 1]])
def test_validate_bbox_rejects_nonsense(bad) -> None:
    with pytest.raises(ValidationError):
        geo.validate_bbox(bad)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("56.12, -3.41", [-3.41, 56.12]),
        ("56.12 -3.41", [-3.41, 56.12]),
        ("POINT(-3.41 56.12)", [-3.41, 56.12]),
        ('{"type": "Point", "coordinates": [-3.41, 56.12]}', [-3.41, 56.12]),
    ],
)
def test_parse_text(text: str, expected) -> None:
    assert geo.parse_text(text)["coordinates"] == expected


def test_parse_text_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        geo.parse_text("near the harbour")


def test_to_text_round_trips() -> None:
    for g in (
        POINT,
        SQUARE,
        {"type": "Point", "coordinates": [-3.41, 56.12, -300]},
    ):
        assert geo.parse_text(geo.to_text(g)) == g


def test_is_geometry_ignores_other_dicts() -> None:
    assert geo.is_geometry(POINT)
    assert not geo.is_geometry({"sha256": "ab", "filename": "x", "size": 1})
    assert not geo.is_geometry("56, -3")


# The same vectors are asserted by frontend/src/utils/geoCoords.test.ts: the
# CLI/CSV reader and the browser must agree on what a typed location means.
COORDINATE_VECTORS = [
    ("56.12, -3.41", (56.12, -3.41)),
    ("56.12 -3.41", (56.12, -3.41)),
    ("56.12N 3.41W", (56.12, -3.41)),
    ("56.12 N, 3.41 W", (56.12, -3.41)),
    ("N56.12 W3.41", (56.12, -3.41)),
    ("3.41W 56.12N", (56.12, -3.41)),
    ("56°07'12\"N 3°24'36\"W", (56.12, -3.41)),
    ("N 56° 07.2' W 3° 24.6'", (56.12, -3.41)),
    ("56°07'12\" -3°24'36\"", (56.12, -3.41)),
    ("56 07 12 N, 3 24 36 W", (56.12, -3.41)),
    ("33.5S 151.2E", (-33.5, 151.2)),
]
COORDINATE_REJECTS = ["nonsense", "56N 3N", "56°75'N 3°W", "-56N 3W", "56", "1 2 3"]


@pytest.mark.parametrize("text,expected", COORDINATE_VECTORS)
def test_parse_coordinates(text, expected) -> None:
    got = geo.parse_coordinates(text)
    assert got == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("text", COORDINATE_REJECTS)
def test_parse_coordinates_rejects(text) -> None:
    assert geo.parse_coordinates(text) is None


def test_parse_text_reads_dms_as_a_point() -> None:
    p = geo.parse_text("56°07'12\"N 3°24'36\"W")
    assert p["coordinates"] == pytest.approx([-3.41, 56.12])


def test_uncertainty_is_validated_and_kept() -> None:
    p = {"type": "Point", "coordinates": [1, 2], "uncertainty_m": 120}
    assert geo.positions(p) == [(1.0, 2.0)]
    for bad in (-1, "10", True):
        with pytest.raises(ValidationError, match="uncertainty_m"):
            geo.positions({**p, "uncertainty_m": bad})
    # a point with extras can't be written as a plain "lat, lon"
    assert geo.parse_text(geo.to_text(p)) == p
