"""Geographic values for `geo` fields.

A value is a GeoJSON geometry object (RFC 7946): ``{"type": "Point",
"coordinates": [lon, lat]}``, WGS84, longitude first. A third coordinate is
read as altitude or depth and is stored untouched. Nothing here reprojects.

A field's `geometry_types` restriction limits the shapes accepted and its
`bbox` restriction ``[west, south, east, north]`` limits where they may be.
West greater than east means the box crosses the antimeridian (the 180th
meridian), which is routine for ocean data.
"""

from __future__ import annotations

import json
import re
from typing import Any

from civex.domain.exceptions import ValidationError

GEOMETRY_TYPES = (
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
)


def _position(pos: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(pos, (list, tuple))
        or len(pos) not in (2, 3)
        or any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in pos)
    ):
        raise ValidationError(f"{where}: a position is [longitude, latitude]")
    lon, lat = float(pos[0]), float(pos[1])
    if not -180 <= lon <= 180:
        raise ValidationError(f"{where}: longitude {lon} is outside -180 to 180")
    if not -90 <= lat <= 90:
        raise ValidationError(f"{where}: latitude {lat} is outside -90 to 90")
    return lon, lat


def _line(coords: Any, where: str, minimum: int = 2) -> list[tuple[float, float]]:
    if not isinstance(coords, (list, tuple)) or len(coords) < minimum:
        raise ValidationError(f"{where}: needs at least {minimum} positions")
    return [_position(p, where) for p in coords]


def _ring(coords: Any, where: str) -> list[tuple[float, float]]:
    ring = _line(coords, where, minimum=4)
    if ring[0] != ring[-1]:
        raise ValidationError(f"{where}: a polygon ring must end where it starts")
    return ring


def positions(geometry: Any) -> list[tuple[float, float]]:
    """Validate *geometry* and return every (lon, lat) in it.

    Raises ValidationError describing the first structural problem.
    """
    if not isinstance(geometry, dict):
        raise ValidationError("a location must be a GeoJSON geometry object")
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    where = str(kind)
    # How well the position is known, in metres (a GPS fix's accuracy, an
    # Argos location class's error radius). A foreign member, as RFC 7946 allows.
    if "uncertainty_m" in geometry:
        u = geometry["uncertainty_m"]
        if isinstance(u, bool) or not isinstance(u, (int, float)) or u < 0:
            raise ValidationError(
                f"{where}: uncertainty_m must be a number of metres, 0 or more"
            )
    if kind == "Point":
        return [_position(coords, where)]
    if kind == "MultiPoint":
        return _line(coords, where, minimum=1)
    if kind == "LineString":
        return _line(coords, where)
    if kind == "MultiLineString":
        return _flatten(coords, where, lambda c: _line(c, where))
    if kind == "Polygon":
        return _flatten(coords, where, lambda c: _ring(c, where))
    if kind == "MultiPolygon":
        out: list[tuple[float, float]] = []
        for poly in _as_list(coords, where):
            out += _flatten(poly, where, lambda c: _ring(c, where))
        return out
    raise ValidationError(
        f"unknown geometry type {kind!r}; use one of {', '.join(GEOMETRY_TYPES)}"
    )


def _as_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValidationError(f"{where}: coordinates are missing")
    return list(value)


def _flatten(coords: Any, where: str, each: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for part in _as_list(coords, where):
        out += each(part)
    return out


def in_bbox(lon: float, lat: float, bbox: list[float]) -> bool:
    west, south, east, north = bbox
    if not south <= lat <= north:
        return False
    if west <= east:
        return west <= lon <= east
    return lon >= west or lon <= east  # crosses the antimeridian


def validate_bbox(bbox: Any) -> list[float]:
    """Check a `bbox` restriction value; returns it as floats."""
    if (
        not isinstance(bbox, (list, tuple))
        or len(bbox) != 4
        or any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in bbox)
    ):
        raise ValidationError("bbox must be [west, south, east, north] in degrees")
    west, south, east, north = (float(n) for n in bbox)
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValidationError("bbox longitudes must be between -180 and 180")
    if not (-90 <= south <= north <= 90):
        raise ValidationError("bbox needs -90 <= south <= north <= 90")
    return [west, south, east, north]


def check(geometry: Any, restrictions: dict[str, Any]) -> None:
    """Validate a stored geometry against a field's restrictions."""
    pts = positions(geometry)
    allowed = restrictions.get("geometry_types")
    if allowed and geometry["type"] not in allowed:
        raise ValidationError(
            f"{geometry['type']} is not allowed; accepted: {', '.join(allowed)}"
        )
    bbox = restrictions.get("bbox")
    if bbox:
        box = validate_bbox(bbox)
        for lon, lat in pts:
            if not in_bbox(lon, lat, box):
                raise ValidationError(
                    f"position {lat}, {lon} is outside the allowed area "
                    f"(west {box[0]}, south {box[1]}, east {box[2]}, north {box[3]})"
                )


_NUM = r"[-+]?\d+(?:\.\d+)?"
_UNSIGNED = r"\d+(?:\.\d+)?"
_LATLON_RE = re.compile(rf"^\s*({_NUM})\s*[, ]\s*({_NUM})\s*$")
_WKT_POINT_RE = re.compile(rf"^\s*POINT\s*\(\s*({_NUM})\s+({_NUM})\s*\)\s*$", re.I)
_SYMBOLS = str.maketrans(
    {
        "\u2032": "'",
        "\u2019": "'",
        "`": "'",
        "\u2033": '"',
        "\u201d": '"',
        "\u00ba": "\u00b0",
        "\u02da": "\u00b0",
        ",": " ",
        ";": " ",
    }
)
_HEMI_SIGN = {"N": 1, "E": 1, "S": -1, "W": -1}


def _sexagesimal(numbers: list[str]) -> float | None:
    """Degrees [minutes [seconds]] as one number, or None if minutes or
    seconds are out of range."""
    if not 1 <= len(numbers) <= 3:
        return None
    parts = [float(n) for n in numbers]
    if any(p >= 60 for p in parts[1:]):
        return None
    return sum(p / 60**i for i, p in enumerate(parts))


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Read a latitude/longitude pair written the ways people write them.

    Returns (latitude, longitude) or None. Accepts decimal degrees
    ("56.12, -3.41"), with hemisphere letters in front or behind
    ("56.12N 3.41W", "N56.12 W3.41", either order), and degrees with minutes
    and seconds ("56°07'12\"N 3°24'36\"W", "N 56° 07.2' W 3° 24.6'",
    "56°07'12\" -3°24'36\""). Ranges are the caller's to check.
    """
    s = text.translate(_SYMBOLS).replace("''", '"').strip()
    hemis = [i for i, c in enumerate(s) if c.upper() in _HEMI_SIGN]
    segments: list[tuple[str, int, str]] = []  # (axis, sign, body)
    if len(hemis) == 2:
        if hemis[0] == 0:  # N 56 07 W 3 24: letter first
            cuts = [(hemis[0], hemis[1]), (hemis[1], len(s))]
            bodies = [(s[a], s[a + 1 : b]) for a, b in cuts]
        else:  # 56 07 N 3 24 W: letter last
            cuts = [(0, hemis[0]), (hemis[0] + 1, hemis[1])]
            bodies = [
                (s[hemis[0]], s[cuts[0][0] : cuts[0][1]]),
                (s[hemis[1]], s[cuts[1][0] : cuts[1][1]]),
            ]
        for letter, body in bodies:
            if "-" in body:
                return None  # a sign and a hemisphere together are ambiguous
            axis = "lat" if letter.upper() in "NS" else "lon"
            segments.append((axis, _HEMI_SIGN[letter.upper()], body))
        if {a for a, _, _ in segments} != {"lat", "lon"}:
            return None
    elif not hemis:
        if re.search(r"[\u00b0'\"]", s):
            parts = re.split(rf"\s+(?={_NUM}\s*\u00b0)", s)
            if len(parts) != 2:
                return None
            for axis, part in zip(("lat", "lon"), parts):
                segments.append(
                    (axis, -1 if part.lstrip().startswith("-") else 1, part)
                )
        else:
            m = _LATLON_RE.match(s)
            return (float(m.group(1)), float(m.group(2))) if m else None
    else:
        return None
    values: dict[str, float] = {}
    for axis, sign, body in segments:
        v = _sexagesimal(re.findall(_UNSIGNED, body))
        if v is None:
            return None
        values[axis] = sign * v
    return values["lat"], values["lon"]


def parse_text(text: str) -> dict[str, Any]:
    """Read a location typed or exported as text.

    Accepts latitude, longitude in any of the forms `parse_coordinates`
    reads, WKT ``POINT(-3.41 56.12)`` (longitude first, as WKT defines it),
    or a GeoJSON string. Raises ValueError if it is none of these.
    """
    m = _WKT_POINT_RE.match(text)
    if m:
        return {"type": "Point", "coordinates": [float(m.group(1)), float(m.group(2))]}
    if not text.lstrip().startswith("{"):
        pair = parse_coordinates(text)
        if pair is not None:
            return {"type": "Point", "coordinates": [pair[1], pair[0]]}
        raise ValueError(f"not a location: {text!r}")
    try:
        obj = json.loads(text)
    except ValueError:
        raise ValueError(f"not a location: {text!r}") from None
    if not isinstance(obj, dict):
        raise ValueError(f"not a location: {text!r}")
    return obj


def is_geometry(value: Any) -> bool:
    """True for a dict shaped like a geometry (used where the field type
    isn't known, e.g. when writing a CSV cell)."""
    return (
        isinstance(value, dict)
        and value.get("type") in GEOMETRY_TYPES
        and "coordinates" in value
    )


def to_text(geometry: dict[str, Any]) -> str:
    """Text for a CSV cell that `parse_text` reads back unchanged.

    A plain point is "latitude, longitude"; anything else (including a point
    that carries a depth or an uncertainty) is compact GeoJSON.
    """
    coords = geometry.get("coordinates")
    if (
        set(geometry) <= {"type", "coordinates"}
        and geometry.get("type") == "Point"
        and isinstance(coords, list)
        and len(coords) == 2
    ):
        return f"{coords[1]}, {coords[0]}"
    return json.dumps(geometry, separators=(",", ":"))
