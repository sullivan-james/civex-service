"""Slug/label helpers in civex.domain.naming.

Mirrored by frontend/src/utils/naming.ts — a change here that isn't made
there shows up as a form that accepts a name the API then rejects with 422.
"""
from __future__ import annotations

import pytest

from civex.domain.exceptions import ValidationError
from civex.domain.naming import display_label, is_slug, slugify, validate_name


@pytest.mark.parametrize(
    "name",
    ["a", "recording_date", "_private", "site2", "x_1_2"],
)
def test_is_slug_accepts_lowercase_identifiers(name: str):
    assert is_slug(name)


@pytest.mark.parametrize(
    "name",
    ["", "Recording Date", "recording-date", "RecordingDate", "2024_count", "a b"],
)
def test_is_slug_rejects_everything_else(name: str):
    assert not is_slug(name)


def test_is_slug_rejects_overlong_names():
    assert not is_slug("a" * 256)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Recording Date", "recording_date"),
        ("Age (years)", "age_years"),
        ("Température", "temperature"),
        ("  spaced  out  ", "spaced_out"),
        ("already_a_slug", "already_a_slug"),
        ("Mixed-CASE/Separators", "mixed_case_separators"),
    ],
)
def test_slugify(text: str, expected: str):
    assert slugify(text) == expected


def test_slugify_prefixes_a_leading_digit_rather_than_dropping_it():
    # "_2024_count", not "count" — the digit is part of the meaning.
    assert slugify("2024 count") == "_2024_count"
    assert is_slug(slugify("2024 count"))


def test_slugify_raises_when_nothing_survives():
    with pytest.raises(ValidationError):
        slugify("!!!")


def test_slugify_truncates_to_the_column_width():
    assert len(slugify("x" * 400)) == 255


def test_validate_name_returns_valid_names_unchanged():
    assert validate_name("recording_date", "field name") == "recording_date"


def test_validate_name_suggests_a_slug_for_a_human_name():
    with pytest.raises(ValidationError) as exc:
        validate_name("Recording Date", "field name")
    assert "recording_date" in str(exc.value)
    assert "label" in str(exc.value)  # points the user at the right escape hatch


def test_validate_name_rejects_empty_and_whitespace():
    for bad in ["", "   "]:
        with pytest.raises(ValidationError):
            validate_name(bad, "field name")


def test_validate_name_rejects_overlong_names_without_dumping_them():
    with pytest.raises(ValidationError) as exc:
        validate_name("a" * 300, "schema name")
    assert len(str(exc.value)) < 200


def test_display_label_prefers_an_explicit_label():
    assert display_label("recording_date", "Date of Recording") == "Date of Recording"


def test_display_label_derives_a_readable_name_when_unset():
    assert display_label("recording_date", None) == "Recording Date"
    assert display_label("recording_date", "") == "Recording Date"
