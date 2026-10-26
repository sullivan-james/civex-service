"""Reading a value out of a file's name: the `from_filename` restriction and
the `civex.extract_from_filename` plugin. Pure, so anything may import it.

A rule's `pattern` is one pattern or a list tried in order, first match wins.
For a `date`/`datetime` a pattern is a token format (`YYYY MM DD HH mm SS`,
anything else raw regex, year, month and day required) or a regex with named
groups (`(?P<year>…)`, `month`, `day`, `hour`, `minute`, `second`); for text
and numbers a regex whose first capture group is the value, else the whole
match. Patterns are searched for anywhere in the name. A datetime comes out
naive: the record service reads it in the field's, else the collection's,
timezone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date as _date, datetime as _dt
from typing import Any

KINDS: frozenset[str] = frozenset({"string", "integer", "float", "date", "datetime"})
DATE_KINDS: frozenset[str] = frozenset({"date", "datetime"})

TOKENS: tuple[str, ...] = ("YYYY", "MM", "DD", "HH", "mm", "SS")
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
    """The regex a token format stands for: each token a named group."""
    parts = _TOKEN_RE.split(fmt)
    return "".join(_TOKEN_MAP[p] if p in _TOKEN_MAP else p for p in parts)


def is_named(pattern: str) -> bool:
    """Whether `pattern` is a regex with named groups, not a token format."""

    return _NAMED_GROUP_RE.search(pattern) is not None


def patterns_of(value: Any) -> tuple[str, ...]:
    """A rule's `pattern` as the patterns to try: one string, or a list."""

    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(v for v in value if isinstance(v, str))
    return ()


def compile_pattern(pattern: str, kind: str) -> re.Pattern[str]:
    """`pattern` as a regex for a value of `kind`, or ValueError saying why not."""

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
    """`raw` read with the token format `fmt` as an ISO date or naive datetime
    (the plugin's two-step form; a format with no date tokens reads as
    1970-01-01, as it always has). ValueError when it doesn't match."""

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
    """The value of `kind` the first matching pattern reads out of `filename`,
    None when none matches. ValueError for a bad pattern or a match that
    isn't a `kind`."""

    for pattern in patterns_of(patterns):
        m = compile_pattern(pattern, kind).search(filename)
        if m is not None:
            return _value_of(m, kind)
    return None


def try_patterns(
    filename: str, patterns: Sequence[str], kind: str
) -> tuple[list[str | None], Any, str | None]:
    """What an editor shows while a rule is typed: each pattern's problem (or
    None), then, when they all compile and there is a name to try, the value
    read and the error reading it. Nothing is saved."""
    problems: list[str | None] = []
    for pattern in patterns:
        try:
            compile_pattern(pattern, kind)
            problems.append(None)
        except ValueError as e:
            problems.append(str(e))
    if not filename or any(problems):
        return problems, None, None
    try:
        return problems, extract(filename, patterns, kind), None
    except ValueError as e:
        return problems, None, str(e)


def _first_file(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, dict) else None


def first_filename(value: Any) -> str | None:
    """The name of the (first) file in a `file`/`file_list` value, or None."""

    ref = _first_file(value)
    name = ref.get("filename") if ref else None
    return name if isinstance(name, str) and name else None


def first_file_key(value: Any) -> tuple[Any, Any] | None:
    """(sha256, filename) of the (first) file, or None: a new name or new
    content is a new file as far as a rule reading the name is concerned."""

    ref = _first_file(value)
    if ref is None:
        return None
    return ref.get("sha256"), ref.get("filename")


def rule_of(restrictions: dict[str, Any] | None) -> tuple[str, tuple[str, ...]] | None:
    """`(file field, patterns)` of a field's rule, or None when absent or malformed."""

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
