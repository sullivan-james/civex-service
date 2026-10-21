"""Reading a value out of a file's name.

The one rule for the `from_filename` restriction (a field filled from a file
field's name as the record is saved) and for the `civex.extract_from_filename`
workflow plugin, which calls in here and adds nothing of its own to the
parsing. Pure: no civex imports, so anything may use it. Mirrored by
`frontend/src/utils/filenameExtract.ts` for the live preview.

A pattern means one of two things, by the kind of value wanted:

- For a `date` or `datetime`, a *token format*: `YYYY MM DD HH mm SS` stand
  for the parts of the date; anything else is a raw regular expression, so
  `YYYYMMDD[-_]HHmmSS` reads both `20240315_093000` and `20240315-093000`.
  The year, month and day tokens are required.
- For text and numbers, a plain regular expression: the first capture group
  is the value, or the whole match when there is none.

The pattern is searched for anywhere in the name, so it needn't describe the
whole of it. A datetime comes out *naive* (no UTC offset): a timestamp in a
file name is wall time where it was recorded, and the record service reads
it in the field's, else the collection's, timezone when it is saved.
"""

from __future__ import annotations

import re
from datetime import date as _date, datetime as _dt
from typing import Any

#: Field types a value can be read out of a file name for.
KINDS: frozenset[str] = frozenset({"string", "integer", "float", "date", "datetime"})
#: Kinds whose pattern is a token format rather than a plain regex.
DATE_KINDS: frozenset[str] = frozenset({"date", "datetime"})

#: The tokens a date pattern may use, in the order a person would list them.
TOKENS: tuple[str, ...] = ("YYYY", "MM", "DD", "HH", "mm", "SS")

_TOKEN_RE = re.compile(r"(YYYY|MM|DD|HH|mm|SS)")
_TOKEN_MAP = {
    "YYYY": r"(?P<year>\d{4})",
    "MM": r"(?P<month>\d{2})",
    "DD": r"(?P<day>\d{2})",
    "HH": r"(?P<hour>\d{2})",
    "mm": r"(?P<minute>\d{2})",
    "SS": r"(?P<second>\d{2})",
}


def token_regex(fmt: str) -> str:
    """The regular expression a token format stands for: each token a named
    group, everything else left as it is."""
    parts = _TOKEN_RE.split(fmt)
    return "".join(_TOKEN_MAP[p] if p in _TOKEN_MAP else p for p in parts)


def compile_pattern(pattern: str, kind: str) -> re.Pattern[str]:
    """`pattern` as a regular expression for a value of `kind`, or ValueError
    saying what is wrong with it: not a kind a name can fill, an empty
    pattern, a date pattern without a year, month and day, or a regular
    expression that doesn't compile."""
    if kind not in KINDS:
        raise ValueError(
            f"a {kind} field can't be filled from a file name "
            f"(only {', '.join(sorted(KINDS))})"
        )
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("the pattern is empty")
    if kind in DATE_KINDS:
        missing = [t for t in ("YYYY", "MM", "DD") if t not in pattern]
        if missing:
            raise ValueError(
                f"a {kind} pattern needs the tokens {' '.join(missing)} "
                f"(it has {', '.join(t for t in TOKENS if t in pattern) or 'none'})"
            )
        regex = token_regex(pattern)
    else:
        regex = pattern
    try:
        return re.compile(regex)
    except re.error as e:
        raise ValueError(f"not a valid regular expression: {e}") from None


def _date_value(groups: dict[str, str | None], kind: str) -> str:
    year = int(groups.get("year") or 1970)
    month = int(groups.get("month") or 1)
    day = int(groups.get("day") or 1)
    hour = int(groups.get("hour") or 0)
    minute = int(groups.get("minute") or 0)
    second = int(groups.get("second") or 0)
    if kind == "date":
        return _date(year, month, day).isoformat()
    return _dt(year, month, day, hour, minute, second).isoformat()


def parse_by_format(raw: str, fmt: str, kind: str) -> str:
    """`raw` read with the token format `fmt` as an ISO date (`kind` "date")
    or naive ISO datetime (anything else). ValueError when the format
    doesn't match or the numbers don't make a date.

    The plugin's two-step form: a capture group first, then this on what it
    captured. Unlike `compile_pattern`, a format with no date tokens is
    allowed and reads as 1970-01-01, as it always has."""
    m = re.search(token_regex(fmt), raw)
    if m is None:
        raise ValueError(f"Format '{fmt}' did not match '{raw}'")
    return _date_value(m.groupdict(), kind)


def extract(filename: str, pattern: str, kind: str) -> Any:
    """The value of `kind` that `pattern` reads out of `filename`: None when
    the pattern doesn't match (the field stays blank), the value otherwise.
    ValueError when the pattern is bad or what it captured isn't a `kind`
    (not a number, not a real date)."""
    regex = compile_pattern(pattern, kind)
    m = regex.search(filename)
    if m is None:
        return None
    if kind in DATE_KINDS:
        try:
            return _date_value(m.groupdict(), kind)
        except ValueError as e:
            raise ValueError(f"'{m.group(0)}' is not a {kind}: {e}") from None
    captured = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
    if kind == "integer":
        try:
            return int(captured)
        except ValueError:
            raise ValueError(f"'{captured}' is not a whole number") from None
    if kind == "float":
        try:
            return float(captured)
        except ValueError:
            raise ValueError(f"'{captured}' is not a number") from None
    return captured


def first_filename(value: Any) -> str | None:
    """The file name in a `file` or `file_list` value (the first file of a
    list), or None when there is no file."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        name = value.get("filename")
        return name if isinstance(name, str) and name else None
    return None


def rule_of(restrictions: dict[str, Any] | None) -> tuple[str, str] | None:
    """The `(file field name, pattern)` of a field's `from_filename` rule, or
    None when it has none or the rule is malformed."""
    rule = (restrictions or {}).get("from_filename")
    if not isinstance(rule, dict):
        return None
    source, pattern = rule.get("field"), rule.get("pattern")
    if not isinstance(source, str) or not isinstance(pattern, str):
        return None
    if not source or not pattern:
        return None
    return source, pattern


__all__ = [
    "DATE_KINDS",
    "KINDS",
    "TOKENS",
    "compile_pattern",
    "extract",
    "first_filename",
    "parse_by_format",
    "rule_of",
    "token_regex",
]
