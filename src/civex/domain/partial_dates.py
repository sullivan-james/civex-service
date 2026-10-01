"""Partial dates: a year ("2019"), a month ("2019-06") or a full day.

A `date` field's `precision` restriction names the *least* precise value it
accepts. `year` accepts all three forms, `month` accepts month and day, `day`
(the default, and the only behaviour before this existed) accepts full dates
only. Values are stored exactly as given; they are never padded to a day,
because "2019-06" is a different statement from "2019-06-01".

For min/max a value is a *period*: the whole period has to fall inside the
bounds. "2020" against `min: 2020-03` fails, since part of it is earlier.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from civex.domain.exceptions import ValidationError

PRECISIONS = ("year", "month", "day")  # coarse to fine

_PATTERNS = {
    "year": re.compile(r"^\d{4}$"),
    "month": re.compile(r"^\d{4}-\d{2}$"),
    "day": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
}


def precision_of(value: str) -> str:
    """The precision a date string is written at. Raises ValueError."""
    text = value.strip()
    for name, pattern in _PATTERNS.items():
        if pattern.match(text):
            return name
    raise ValueError(f"not a year, month or day: {value!r}")


def period(value: str) -> tuple[date, date]:
    """First and last day covered by *value*. Raises ValueError."""
    text = value.strip()
    kind = precision_of(text)
    if kind == "day":
        d = date.fromisoformat(text)
        return d, d
    year = int(text[:4])
    if year < 1:
        raise ValueError(f"year out of range: {value!r}")
    if kind == "year":
        return date(year, 1, 1), date(year, 12, 31)
    month = int(text[5:7])
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range: {value!r}")
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def normalise(value: str) -> str:
    """Canonical string for a valid partial date (strips whitespace)."""
    text = value.strip()
    period(text)  # validates
    return text


def check_precision(value: str, least_precise: str) -> None:
    """Raise ValidationError if *value* is less precise than allowed."""
    if least_precise not in PRECISIONS:
        return  # malformed restriction; validated when the field is saved
    if PRECISIONS.index(precision_of(value)) < PRECISIONS.index(least_precise):
        raise ValidationError(
            f"'{value}' is less precise than allowed: "
            f"needs at least {least_precise} precision"
        )


def check_bounds(value: str, minimum: str | None, maximum: str | None) -> str | None:
    """A problem description if the period of *value* leaves the bounds."""
    start, end = period(value)
    if minimum is not None and start < period(str(minimum))[0]:
        return f"{value} is before minimum ({minimum})"
    if maximum is not None and end > period(str(maximum))[1]:
        return f"{value} is after maximum ({maximum})"
    return None
