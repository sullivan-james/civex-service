from __future__ import annotations

import pytest

from civex.domain import units
from civex.domain.exceptions import ValidationError


def test_same_unit_is_untouched() -> None:
    assert units.convert(312.4, "m", "m") == 312.4


@pytest.mark.parametrize(
    "value,src,dst,expected",
    [
        (1024, "ft", "m", 312.1152),
        (312.4, "m", "ft", 1024.934383),
        (1, "fathom", "m", 1.8288),
        (1, "nmi", "km", 1.852),
        (0, "°C", "K", 273.15),
        (32, "°F", "°C", 0.0),
        (100, "°C", "°F", 212.0),
        (1013.25, "hPa", "dbar", 10.1325),
        (90, "min", "h", 1.5),
        (10, "kn", "m/s", 5.14444),
    ],
)
def test_convert(value, src, dst, expected) -> None:
    assert units.convert(value, src, dst) == pytest.approx(expected, rel=1e-5)


def test_round_trip_is_stable() -> None:
    assert units.convert(units.convert(312.4, "m", "ft"), "ft", "m") == pytest.approx(
        312.4
    )


def test_aliases() -> None:
    assert units.canonical("degC") == "°C"
    assert units.convert(0, "degC", "K") == pytest.approx(273.15)


def test_different_dimensions_refuse() -> None:
    with pytest.raises(ValidationError, match="length.*time"):
        units.convert(1, "m", "s")


def test_unknown_unit_refuses_conversion() -> None:
    with pytest.raises(ValidationError, match="not a convertible unit"):
        units.convert(1, "umol/kg", "m")


@pytest.mark.parametrize("sym", ["m", "umol/kg", "°C", "degC"])
def test_validate_symbol_accepts(sym: str) -> None:
    assert units.validate_symbol(sym)


@pytest.mark.parametrize("sym", ["", "  ", 5, None, "metres per second", "x" * 30])
def test_validate_symbol_rejects(sym) -> None:
    with pytest.raises(ValidationError):
        units.validate_symbol(sym)


def test_dimension_of() -> None:
    assert units.dimension_of("ft") == "length"
    assert units.dimension_of("umol/kg") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1024", (1024.0, None)),
        ("1024 ft", (1024.0, "ft")),
        ("-3.5e2 m", (-350.0, "m")),
        ("12°C", (12.0, "°C")),
    ],
)
def test_parse_quantity(text, expected) -> None:
    assert units.parse_quantity(text) == expected


def test_parse_quantity_rejects_text() -> None:
    with pytest.raises(ValueError):
        units.parse_quantity("deep")


def test_to_field_unit() -> None:
    assert (
        units.to_field_unit("312.4", "m") == 312.4
    )  # bare number is already in the unit
    assert units.to_field_unit("1024 ft", "m") == pytest.approx(312.1152)
    assert units.to_field_unit("312.4 m", "m") == 312.4
    assert units.to_field_unit("5", None) == 5.0


def test_a_unit_on_a_unitless_field_is_an_error() -> None:
    with pytest.raises(ValidationError, match="has none"):
        units.to_field_unit("1024 ft", None)
