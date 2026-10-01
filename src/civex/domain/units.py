"""Units for numeric fields.

A field has exactly one unit and every stored value is in it. Conversion only
happens at the edges where data enters (CSV import, CLI, the record form):
``convert()`` turns "1024 ft" into the metres a depth field stores. The
service layer never converts; it only checks the unit symbol.

The table covers units that can be converted. A field may also carry any other
symbol (say ``umol/kg``) as a plain label: it is shown but nothing can be
converted to or from it, so entry in that field is always in the stated unit.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from civex.domain.exceptions import ValidationError


class Unit(NamedTuple):
    dimension: str
    factor: float  # value in the dimension's base unit = value * factor + offset
    offset: float = 0.0


UNITS: dict[str, Unit] = {
    # length, base m
    "m": Unit("length", 1.0),
    "mm": Unit("length", 0.001),
    "cm": Unit("length", 0.01),
    "km": Unit("length", 1000.0),
    "in": Unit("length", 0.0254),
    "ft": Unit("length", 0.3048),
    "fathom": Unit("length", 1.8288),
    "nmi": Unit("length", 1852.0),
    # temperature, base °C
    "°C": Unit("temperature", 1.0),
    "K": Unit("temperature", 1.0, -273.15),
    "°F": Unit("temperature", 5.0 / 9.0, -160.0 / 9.0),
    # pressure, base dbar (depth in the sea is about 1 dbar per metre)
    "dbar": Unit("pressure", 1.0),
    "Pa": Unit("pressure", 0.0001),
    "hPa": Unit("pressure", 0.01),
    "kPa": Unit("pressure", 0.1),
    "bar": Unit("pressure", 10.0),
    # time, base s
    "s": Unit("time", 1.0),
    "min": Unit("time", 60.0),
    "h": Unit("time", 3600.0),
    "d": Unit("time", 86400.0),
    # speed, base m/s
    "m/s": Unit("speed", 1.0),
    "km/h": Unit("speed", 1000.0 / 3600.0),
    "kn": Unit("speed", 1852.0 / 3600.0),
    # mass, base kg
    "g": Unit("mass", 0.001),
    "kg": Unit("mass", 1.0),
    "lb": Unit("mass", 0.45359237),
}

# Typed variants people actually write.
ALIASES = {
    "degC": "°C",
    "C": "°C",
    "degF": "°F",
    "F": "°F",
    "knot": "kn",
    "knots": "kn",
}

MAX_SYMBOL_LENGTH = 24


def canonical(symbol: str) -> str:
    """The table's spelling of *symbol* (aliases resolved), else as given."""
    s = symbol.strip()
    return ALIASES.get(s, s)


def validate_symbol(symbol: object) -> str:
    """Check a `unit` restriction value; returns the canonical symbol."""
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValidationError("unit must be a non-empty text symbol such as 'm'")
    s = canonical(symbol)
    if len(s) > MAX_SYMBOL_LENGTH or re.search(r"\s", s):
        raise ValidationError(
            f"unit '{symbol}' must be a short symbol with no spaces, e.g. 'm' or 'umol/kg'"
        )
    return s


def dimension_of(symbol: str) -> str | None:
    unit = UNITS.get(canonical(symbol))
    return unit.dimension if unit else None


def convert(value: float, source: str, target: str) -> float:
    """Convert *value* from unit *source* to *target*.

    Raises ValidationError if either unit is unknown to the table or they
    measure different things.
    """
    src, dst = canonical(source), canonical(target)
    if src == dst:
        return value
    a, b = UNITS.get(src), UNITS.get(dst)
    if a is None or b is None:
        unknown = source if a is None else target
        raise ValidationError(
            f"Can't convert between '{source}' and '{target}': "
            f"'{unknown}' is not a convertible unit"
        )
    if a.dimension != b.dimension:
        raise ValidationError(
            f"Can't convert {source} ({a.dimension}) to {target} ({b.dimension})"
        )
    base = value * a.factor + a.offset
    return (base - b.offset) / b.factor


_QUANTITY_RE = re.compile(
    r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(\S.*?)?\s*$"
)


def parse_quantity(text: str) -> tuple[float, str | None]:
    """Split "1024 ft" into (1024.0, "ft"); a bare number has no unit.
    Raises ValueError for anything else."""
    m = _QUANTITY_RE.match(text)
    if not m:
        raise ValueError(f"not a number or quantity: {text!r}")
    unit = canonical(m.group(2)) if m.group(2) else None
    return float(m.group(1)), unit


def to_field_unit(text: str, field_unit: str | None) -> float:
    """Read typed or imported text for a field stored in *field_unit*.

    A bare number is taken to already be in the field's unit. "1024 ft"
    is converted. A unit on a field that has none is an error rather than
    being dropped: the number would silently change meaning.
    """
    value, given = parse_quantity(text)
    if given is None:
        return value
    if field_unit is None:
        raise ValidationError(
            f"'{text}' has a unit but this field has none; enter just the number"
        )
    return convert(value, given, field_unit)
