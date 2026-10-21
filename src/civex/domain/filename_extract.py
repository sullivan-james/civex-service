"""Reading a value out of a file's name.

The one rule for the `from_filename` restriction (a field filled from a file
field's name as the record is saved) and for the `civex.extract_from_filename`
workflow plugin, which calls in here and adds nothing of its own to the
parsing. Pure: no civex imports, so anything may use it. Mirrored by
`frontend/src/utils/filenameExtract.ts` for the live preview; the two are
tested against the same table of examples.

A rule's `pattern` is one pattern or a list tried in order, first match wins
(so a field can read file names written two ways). A pattern takes one of
three forms:

- For a `date` or `datetime`, a *token format*: `YYYY MM DD HH mm SS` stand
  for the parts of the date; anything else is a raw regular expression, so
  `YYYYMMDD[-_]HHmmSS` reads both `20240315_093000` and `20240315-093000`.
  The year, month and day tokens are required.
- For a `date` or `datetime`, a regular expression with *named groups* for
  the parts (`(?P<year>\\d{4})`, `month`, `day`, `hour`, `minute`,
  `second`): a pattern that has named groups is read this way. Year, month
  and day are required.
- For text and numbers, a plain regular expression: the first capture group
  is the value, or the whole match when there is none.

The pattern is searched for anywhere in the name, so it needn't describe the
whole of it. A datetime comes out *naive* (no UTC offset): a timestamp in a
file name is wall time where it was recorded, and the record service reads
it in the field's, else the collection's, timezone when it is saved.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date as _date, datetime as _dt
from typing import Any

#: Field types a value can be read out of a file name for.
KINDS: frozenset[str] = frozenset({"string", "integer", "float", "date", "datetime"})
#: Kinds whose pattern names the parts of a date (tokens or named groups).
DATE_KINDS: frozenset[str] = frozenset({"date", "datetime"})

#: The tokens a date pattern may use, in the order a person would list them.
TOKENS: tuple[str, ...] = ("YYYY", "MM", "DD", "HH", "mm", "SS")
#: The named groups a date regex may use, in the same order.
DATE_PARTS: tuple[str, ...] = ("year", "month", "day", "hour", "minute", "second")
_REQUIRED_TOKENS = ("YYYY", "MM", "DD")
_REQUIRED_PARTS = ("year", "month", "day")

_TOKEN_RE = re.compile(r"(YYYY|MM|DD|HH|mm|SS)")
_TOKEN_MAP = {
    "YYYY": r"(?P<year>\d{4})",
    "MM": r"(?P<month>\d{2})",
    "DD": r"(?P<day>\d{2})",
    "HH": r"(?P<hour>\d{2})",
    "mm": r"(?P<minute>\d{2})",
    "SS": r"(?P<second>\d{2})",
}
_NAMED_GROUP_RE = re.compile(r"\(\?P<(\w+)>")


def token_regex(fmt: str) -> str:
    """The regular expression a token format stands for: each token a named
    group, everything else left as it is."""
    parts = _TOKEN_RE.split(fmt)
    return "".join(_TOKEN_MAP[p] if p in _TOKEN_MAP else p for p in parts)


def is_named(pattern: str) -> bool:
    """Whether `pattern` is a regular expression with named groups (the
    second form), rather than a token format."""
    return _NAMED_GROUP_RE.search(pattern) is not None


def patterns_of(value: Any) -> tuple[str, ...]:
    """A rule's `pattern` as the patterns to try, in order: one string, or a
    list of them. Anything else is no patterns."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(v for v in value if isinstance(v, str))
    return ()


def compile_pattern(pattern: str, kind: str) -> re.Pattern[str]:
    """`pattern` as a regular expression for a value of `kind`, or ValueError
    saying what is wrong with it: not a kind a name can fill, an empty
    pattern, a date pattern without a year, month and day (tokens or named
    groups), or a regular expression that doesn't compile."""
    if kind not in KINDS:
        raise ValueError(
            f"a {kind} field can't be filled from a file name "
            f"(only {', '.join(sorted(KINDS))})"
        )
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("the pattern is empty")
    if kind in DATE_KINDS:
        if is_named(pattern):
            names = set(_NAMED_GROUP_RE.findall(pattern))
            missing = [p for p in _REQUIRED_PARTS if p not in names]
            if missing:
                raise ValueError(
                    f"a {kind} pattern with named groups needs "
                    f"{', '.join(missing)} (the groups are {' '.join(DATE_PARTS)})"
                )
            unknown = sorted(names - set(DATE_PARTS))
            if unknown:
                raise ValueError(
                    f"unknown group(s) {', '.join(unknown)}: a {kind} pattern's "
                    f"groups are {' '.join(DATE_PARTS)}"
                )
            regex = pattern
        else:
            missing_tokens = [t for t in _REQUIRED_TOKENS if t not in pattern]
            if missing_tokens:
                raise ValueError(
                    f"a {kind} pattern needs the tokens {' '.join(missing_tokens)} "
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


def _value_of(m: re.Match[str], kind: str) -> Any:
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


def extract(filename: str, patterns: str | Sequence[str], kind: str) -> Any:
    """The value of `kind` that `patterns` (one, or several tried in order,
    the first that matches deciding) read out of `filename`: None when none
    matches (the field stays blank), the value otherwise. ValueError when a
    pattern is bad or what the matching one captured isn't a `kind` (not a
    number, not a real date)."""
    for pattern in patterns_of(patterns):
        m = compile_pattern(pattern, kind).search(filename)
        if m is not None:
            return _value_of(m, kind)
    return None


def first_filename(value: Any) -> str | None:
    """The file name in a `file` or `file_list` value (the first file of a
    list), or None when there is no file."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        name = value.get("filename")
        return name if isinstance(name, str) and name else None
    return None


def rule_of(restrictions: dict[str, Any] | None) -> tuple[str, tuple[str, ...]] | None:
    """The `(file field name, patterns)` of a field's `from_filename` rule, or
    None when it has none or the rule is malformed (no field, no patterns,
    or a blank one among them)."""
    rule = (restrictions or {}).get("from_filename")
    if not isinstance(rule, dict):
        return None
    source = rule.get("field")
    patterns = patterns_of(rule.get("pattern"))
    if not isinstance(source, str) or not source:
        return None
    if not patterns or any(not p.strip() for p in patterns):
        return None
    return source, patterns


__all__ = [
    "DATE_KINDS",
    "DATE_PARTS",
    "KINDS",
    "TOKENS",
    "compile_pattern",
    "extract",
    "first_filename",
    "is_named",
    "parse_by_format",
    "patterns_of",
    "rule_of",
    "token_regex",
]
