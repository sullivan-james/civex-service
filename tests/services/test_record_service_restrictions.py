"""Coverage for `_check_restrictions` in record_service.py — the single source
of truth for field validation (see CLAUDE.md "Field restrictions" table).
"""
from __future__ import annotations

import pytest

from civex.domain.exceptions import ValidationError
from civex.services.record_service import _check_restrictions, _parse_datetime


# ---------------------------------------------------------------------------
# value is None: restrictions never apply, regardless of dtype
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dtype", ["integer", "float", "string", "date", "datetime", "file", "url"])
def test_none_value_always_passes(dtype: str) -> None:
    _check_restrictions(None, dtype, {"min": 10, "choices": ["a"]}, "f")


# ---------------------------------------------------------------------------
# integer / float: min / max
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dtype,value", [("integer", 5), ("float", 5.0)])
def test_numeric_within_bounds_passes(dtype: str, value) -> None:
    _check_restrictions(value, dtype, {"min": 0, "max": 10}, "f")


@pytest.mark.parametrize("dtype,value", [("integer", 5), ("float", 5.0)])
def test_numeric_at_boundary_passes(dtype: str, value) -> None:
    _check_restrictions(value, dtype, {"min": value, "max": value}, "f")


def test_numeric_below_min_raises() -> None:
    with pytest.raises(ValidationError, match="below minimum"):
        _check_restrictions(-1, "integer", {"min": 0}, "f")


def test_numeric_above_max_raises() -> None:
    with pytest.raises(ValidationError, match="exceeds maximum"):
        _check_restrictions(11, "integer", {"max": 10}, "f")


# ---------------------------------------------------------------------------
# string: choices / max_length
# ---------------------------------------------------------------------------

def test_string_choice_allowed_passes() -> None:
    _check_restrictions("left", "string", {"choices": ["left", "right"]}, "f")


def test_string_choice_disallowed_raises() -> None:
    with pytest.raises(ValidationError, match="must be one of"):
        _check_restrictions("up", "string", {"choices": ["left", "right"]}, "f")


def test_string_max_length_at_boundary_passes() -> None:
    _check_restrictions("abc", "string", {"max_length": 3}, "f")


def test_string_max_length_exceeded_raises() -> None:
    with pytest.raises(ValidationError, match="exceeds max_length"):
        _check_restrictions("abcd", "string", {"max_length": 3}, "f")


# ---------------------------------------------------------------------------
# enum: choices
# ---------------------------------------------------------------------------

def test_enum_choice_disallowed_raises() -> None:
    with pytest.raises(ValidationError, match="must be one of"):
        _check_restrictions("green", "enum", {"choices": ["red", "blue"]}, "f")


# ---------------------------------------------------------------------------
# url: always validated, independent of the `restrictions` dict
# ---------------------------------------------------------------------------

def test_url_missing_scheme_raises_even_with_no_restrictions() -> None:
    with pytest.raises(ValidationError, match="not a valid URL"):
        _check_restrictions("example.com", "url", {}, "f")


def test_url_with_scheme_passes() -> None:
    _check_restrictions("https://example.com", "url", {}, "f")


# ---------------------------------------------------------------------------
# date / datetime: min / max compared as parsed objects, not raw strings
# ---------------------------------------------------------------------------

def test_date_before_min_raises() -> None:
    with pytest.raises(ValidationError, match="before minimum"):
        _check_restrictions("2024-01-01", "date", {"min": "2024-06-01"}, "f")


def test_date_after_max_raises() -> None:
    with pytest.raises(ValidationError, match="after maximum"):
        _check_restrictions("2024-12-01", "date", {"max": "2024-06-01"}, "f")


def test_date_within_bounds_passes() -> None:
    _check_restrictions("2024-03-01", "date", {"min": "2024-01-01", "max": "2024-06-01"}, "f")


def test_datetime_comparison_uses_actual_instant_not_lexicographic_order() -> None:
    """A naive string comparison of these two ISO strings would conclude the
    value is *greater* than min (since '10' > '04' lexicographically at the
    hour position) — but the value's actual UTC instant (10:00Z) is before
    the min's actual UTC instant (04:00-08:00 == 12:00Z). The min/max check
    must compare parsed datetime objects, which correctly account for the
    differing UTC offsets, to catch this."""
    with pytest.raises(ValidationError, match="before minimum"):
        _check_restrictions(
            "2024-06-01T10:00:00+00:00",
            "datetime",
            {"min": "2024-06-01T04:00:00-08:00"},
            "f",
        )


def test_datetime_malformed_restriction_is_ignored() -> None:
    # Malformed min/max shouldn't crash validation — the value was already
    # normalised, so a bad restriction is treated as "no restriction."
    _check_restrictions("2024-06-01T00:00:00+00:00", "datetime", {"min": "not-a-date"}, "f")


# ---------------------------------------------------------------------------
# file / file_list: accept (extension allowlist) / max_size
# ---------------------------------------------------------------------------

def test_file_disallowed_extension_raises() -> None:
    ref = {"sha256": "a" * 64, "filename": "notes.txt", "size": 10}
    with pytest.raises(ValidationError, match="not allowed"):
        _check_restrictions(ref, "file", {"accept": ".csv,.pdf"}, "f")


def test_file_allowed_extension_passes() -> None:
    ref = {"sha256": "a" * 64, "filename": "notes.csv", "size": 10}
    _check_restrictions(ref, "file", {"accept": ".csv,.pdf"}, "f")


def test_file_exceeds_max_size_raises() -> None:
    ref = {"sha256": "a" * 64, "filename": "big.csv", "size": 1000}
    with pytest.raises(ValidationError, match="exceeds max_size"):
        _check_restrictions(ref, "file", {"max_size": 500}, "f")


def test_file_list_checks_every_ref() -> None:
    good = {"sha256": "a" * 64, "filename": "a.csv", "size": 10}
    bad = {"sha256": "b" * 64, "filename": "b.exe", "size": 10}
    with pytest.raises(ValidationError, match="not allowed"):
        _check_restrictions([good, bad], "file_list", {"accept": ".csv"}, "f")


# ---------------------------------------------------------------------------
# naive datetimes are assumed UTC on ingest
# ---------------------------------------------------------------------------

def test_naive_datetime_assumed_utc() -> None:
    assert _parse_datetime("2024-01-01T12:00:00") == "2024-01-01T12:00:00+00:00"


def test_aware_datetime_converted_to_utc() -> None:
    assert _parse_datetime("2024-01-01T12:00:00-05:00") == "2024-01-01T17:00:00+00:00"


def test_datetime_local_input_missing_seconds_is_accepted() -> None:
    # <input type="datetime-local"> values omit seconds.
    assert _parse_datetime("2024-01-01T12:00") == "2024-01-01T12:00:00+00:00"
