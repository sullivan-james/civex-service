from __future__ import annotations

import pytest

from civex.domain.exceptions import ValidationError
from civex.domain.timezones import parse_datetime, validate_timezone

CHICAGO = "America/Chicago"


def test_validate_accepts_iana_names_and_strips() -> None:
    assert validate_timezone(" America/Chicago ") == "America/Chicago"
    assert validate_timezone("UTC") == "UTC"


@pytest.mark.parametrize("bad", ["", "  ", "Mars/Olympus", "../etc/passwd", "America"])
def test_validate_rejects_unknown(bad: str) -> None:
    with pytest.raises(ValidationError, match="Unknown timezone"):
        validate_timezone(bad)


def test_naive_without_zone_is_utc() -> None:
    assert parse_datetime("2024-03-01T15:30:00") == "2024-03-01T15:30:00+00:00"


def test_naive_without_seconds() -> None:
    assert parse_datetime("2024-03-01T15:30") == "2024-03-01T15:30:00+00:00"


def test_naive_read_in_zone_standard_time() -> None:
    # CST is UTC-6
    assert parse_datetime("2024-03-01T15:30", CHICAGO) == "2024-03-01T21:30:00+00:00"


def test_naive_read_in_zone_daylight_time() -> None:
    # CDT is UTC-5
    assert parse_datetime("2024-07-01T15:30", CHICAGO) == "2024-07-01T20:30:00+00:00"


def test_half_hour_offset_zone() -> None:
    assert (
        parse_datetime("2024-03-01T12:00", "Asia/Kolkata")
        == "2024-03-01T06:30:00+00:00"
    )


def test_explicit_offset_wins_over_zone() -> None:
    assert (
        parse_datetime("2024-01-01T12:00:00-05:00", "Asia/Kolkata")
        == "2024-01-01T17:00:00+00:00"
    )
    assert (
        parse_datetime("2024-01-01T12:00:00Z", CHICAGO) == "2024-01-01T12:00:00+00:00"
    )


def test_nonexistent_time_is_rejected() -> None:
    # 2024-03-10 02:30 doesn't exist in Chicago: clocks jump 02:00 -> 03:00
    with pytest.raises(ValidationError, match="does not exist"):
        parse_datetime("2024-03-10T02:30", CHICAGO)


def test_ambiguous_time_is_rejected() -> None:
    # 2024-11-03 01:30 happens twice in Chicago
    with pytest.raises(ValidationError, match="ambiguous"):
        parse_datetime("2024-11-03T01:30", CHICAGO)


def test_times_either_side_of_a_transition_are_fine() -> None:
    assert parse_datetime("2024-03-10T01:59", CHICAGO) == "2024-03-10T07:59:00+00:00"
    assert parse_datetime("2024-03-10T03:00", CHICAGO) == "2024-03-10T08:00:00+00:00"
    assert parse_datetime("2024-11-03T00:59", CHICAGO) == "2024-11-03T05:59:00+00:00"
    assert parse_datetime("2024-11-03T02:00", CHICAGO) == "2024-11-03T08:00:00+00:00"


def test_offset_resolves_an_ambiguous_time() -> None:
    assert (
        parse_datetime("2024-11-03T01:30:00-05:00", CHICAGO)
        == "2024-11-03T06:30:00+00:00"
    )
    assert (
        parse_datetime("2024-11-03T01:30:00-06:00", CHICAGO)
        == "2024-11-03T07:30:00+00:00"
    )


def test_utc_zone_has_no_transitions() -> None:
    assert parse_datetime("2024-11-03T01:30", "UTC") == "2024-11-03T01:30:00+00:00"


def test_malformed_input_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_datetime("not a date", CHICAGO)
