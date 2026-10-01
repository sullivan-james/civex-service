from __future__ import annotations

from datetime import date

import pytest

from civex.domain import partial_dates as pd
from civex.domain.exceptions import ValidationError


@pytest.mark.parametrize(
    "text,kind",
    [("2019", "year"), ("2019-06", "month"), ("2019-06-14", "day"), (" 2019 ", "year")],
)
def test_precision_of(text: str, kind: str) -> None:
    assert pd.precision_of(text) == kind


@pytest.mark.parametrize("text", ["19", "2019-6", "2019-06-1", "June 2019", "", "2019-06-14T00:00"])
def test_precision_of_rejects_other_shapes(text: str) -> None:
    with pytest.raises(ValueError):
        pd.precision_of(text)


def test_period_covers_whole_span() -> None:
    assert pd.period("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    assert pd.period("2023") == (date(2023, 1, 1), date(2023, 12, 31))
    assert pd.period("2023-05-04") == (date(2023, 5, 4), date(2023, 5, 4))


@pytest.mark.parametrize("text", ["2023-13", "2023-00", "2023-02-30", "0000"])
def test_period_rejects_impossible_dates(text: str) -> None:
    with pytest.raises(ValueError):
        pd.period(text)


def test_normalise_keeps_precision() -> None:
    assert pd.normalise(" 2019-06 ") == "2019-06"


@pytest.mark.parametrize(
    "value,least,ok",
    [
        ("2019", "year", True),
        ("2019-06", "year", True),
        ("2019-06-14", "year", True),
        ("2019", "month", False),
        ("2019-06", "month", True),
        ("2019-06", "day", False),
        ("2019-06-14", "day", True),
    ],
)
def test_check_precision(value: str, least: str, ok: bool) -> None:
    if ok:
        pd.check_precision(value, least)
    else:
        with pytest.raises(ValidationError, match="precision"):
            pd.check_precision(value, least)


def test_bounds_require_the_whole_period_inside() -> None:
    assert pd.check_bounds("2020-03", "2020-03", "2020-03") is None
    assert "before minimum" in (pd.check_bounds("2020", "2020-03", None) or "")
    assert "after maximum" in (pd.check_bounds("2020", None, "2020-06") or "")
    assert pd.check_bounds("2020-05-01", "2020", "2020") is None
    assert "before minimum" in (pd.check_bounds("2019-12-31", "2020-01-01", None) or "")
