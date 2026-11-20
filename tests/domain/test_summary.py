"""What a summary may ask of each field type, and how keys read."""

from __future__ import annotations

from datetime import datetime

import pytest

from civex.domain.exceptions import ValidationError
from civex.domain.field_descriptors import FIELD_TYPES
from civex.domain.summary import (
    MEASURES,
    GroupBy,
    Measure,
    SummaryRequest,
    group_problem,
    measure_problem,
    parse_group_by,
    parse_measure,
    period_bounds,
    precision_label,
)
from civex.domain.timezones import offset_changes


def test_each_type_allows_known_measures_and_groupings() -> None:
    for d in FIELD_TYPES.values():
        assert set(d.measures) <= set(MEASURES) - {"count"}, d.type
        assert "filled" in d.measures, d.type
        assert d.grouping in (None, "value", "bin", "bucket", "each"), d.type
        assert bool(d.buckets) == (d.grouping == "bucket"), d.type
    numbers = {"filled", "distinct", "min", "max", "mean", "sum"}
    assert set(FIELD_TYPES["float"].measures) == numbers
    assert set(FIELD_TYPES["integer"].measures) == numbers
    assert {"mean", "sum"}.isdisjoint(FIELD_TYPES["date"].measures)
    assert {"min", "max"} <= set(FIELD_TYPES["datetime"].measures)
    for t in ("geo", "file", "file_list", "longtext"):
        assert FIELD_TYPES[t].measures == ("filled",)
        assert FIELD_TYPES[t].grouping is None


def test_problems() -> None:
    assert measure_problem("mean", "float", "depth") is None
    assert "mean" in (measure_problem("mean", "string", "label") or "")
    assert group_problem(GroupBy("d", bin=5), "float", "d") is None
    assert group_problem(GroupBy("d", bin=0), "float", "d")
    assert group_problem(GroupBy("d", bucket="month"), "date", "d") is None
    assert group_problem(GroupBy("d", bucket="month"), "integer", "d")
    assert group_problem(GroupBy("g"), "geo", "g")


def test_request_shape() -> None:
    SummaryRequest([GroupBy("a")], [Measure("count")]).check()
    for bad in (
        SummaryRequest([GroupBy(str(i)) for i in range(4)]),
        SummaryRequest(measures=[]),
        SummaryRequest(measures=[Measure("median", "a")]),
        SummaryRequest(measures=[Measure("count", "a")]),
        SummaryRequest(measures=[Measure("mean")]),
        SummaryRequest([GroupBy("a"), GroupBy("a")]),
        SummaryRequest(limit=0),
    ):
        with pytest.raises(ValidationError):
            bad.check()


def test_written_forms() -> None:
    assert parse_group_by("site.region") == GroupBy("region", "site")
    assert parse_group_by("taken:month") == GroupBy("taken", bucket="month")
    assert parse_group_by("depth:2.5") == GroupBy("depth", bin=2.5)
    assert parse_group_by("depth:5").key == "depth:5"
    with pytest.raises(ValidationError):
        parse_group_by("depth:fortnight")
    assert parse_measure("count") == Measure("count")
    assert parse_measure("mean:site.depth") == Measure("mean", "depth", "site")
    assert parse_measure("mean:site.depth").key == "mean:site.depth"


def test_periods() -> None:
    assert period_bounds("2019", "month") == ("year", "2019", "2020")
    assert period_bounds("2019-12", "month") == ("month", "2019-12", "2020-01")
    assert period_bounds("2019-06-10", "week") == ("day", "2019-06-10", "2019-06-17")
    assert period_bounds("soon", "year") is None
    assert precision_label("2019", "year", "month") == "2019, month not known"
    assert precision_label("2019-06", "month", "week") == "2019-06, week not known"
    assert precision_label("2019-06-10", "day", "week") == "Week of 2019-06-10"


def test_offset_changes_match_the_zone() -> None:
    first, changes = offset_changes("Europe/London")
    in_2024 = [c for c in changes if c[0].year == 2024]
    assert in_2024 == [
        (datetime(2024, 3, 31, 1, 0), 60),
        (datetime(2024, 10, 27, 1, 0), 0),
    ]
    assert offset_changes("UTC") == (0, ())
