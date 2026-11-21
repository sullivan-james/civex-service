"""The formula language (`domain/formulas.py`): what it reads, what it
refuses, and what it gives for each operator and function."""

from __future__ import annotations

import pytest

from civex.domain import formulas as F
from civex.domain.exceptions import ValidationError

NUMS = {"a": "float", "b": "float", "n": "integer"}


def calc(source, values=None, dtypes=None, result="float", decimals=None):
    return F.compute(F.parse(source), values or {}, dtypes or {}, result, decimals)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("a + b", 7.0),
        ("a - b", 3.0),
        ("a * b", 10.0),
        ("a / b", 2.5),
        ("a // b", 2.0),
        ("a % b", 1.0),
        ("a ** b", 25.0),
        ("-a", -5.0),
        ("+a", 5.0),
        ("round(a / 3, 2)", 1.67),
        ("abs(b - a)", 3.0),
        ("min(a, b, 9)", 2.0),
        ("max(a, b)", 5.0),
        ("sqrt(a * 5)", 5.0),
        ("log(100, 10)", 2.0),
        ("floor(a / b)", 2.0),
        ("ceil(a / b)", 3.0),
        ("exp(0)", 1.0),
    ],
)
def test_arithmetic_and_number_functions(source, expected):
    assert calc(source, {"a": 5, "b": 2}, NUMS) == (expected, None)


def test_comparisons_logic_and_conditionals():
    vals, types = {"a": 5, "b": 2}, NUMS
    assert calc("a > b", vals, types, "boolean") == (True, None)
    assert calc("b < a <= 5", vals, types, "boolean") == (True, None)
    assert calc("a == b or a != b", vals, types, "boolean") == (True, None)
    assert calc("not (a > b and b > a)", vals, types, "boolean") == (True, None)
    assert calc('"deep" if a > 3 else "shallow"', vals, types, "string") == (
        "deep",
        None,
    )


def test_text_functions():
    vals = {"site": "North", "code": 7, "tags": ["x", "y"]}
    types = {"site": "string", "code": "integer", "tags": "tags"}
    assert calc('concat(site, "-", code)', vals, types, "string") == ("North-7", None)
    assert calc('site + "!"', vals, types, "string") == ("North!", None)
    assert calc("upper(site)", vals, types, "string") == ("NORTH", None)
    assert calc("lower(site)", vals, types, "string") == ("north", None)
    assert calc("len(site)", vals, types, "integer") == (5, None)
    assert calc("len(tags)", vals, types, "integer") == (2, None)
    assert calc("str(code)", vals, types, "string") == ("7", None)


def test_dates_and_times():
    vals = {
        "start": "2024-01-30",
        "end": "2024-03-01",
        "t0": "2024-01-01T00:00:00+00:00",
        "t1": "2024-01-02T06:00:00+00:00",
        "season": "2019",
    }
    types = {
        "start": "date",
        "end": "date",
        "t0": "datetime",
        "t1": "datetime",
        "season": "date",
    }
    assert calc("days_between(start, end)", vals, types, "integer") == (31, None)
    assert calc("hours_between(t0, t1)", vals, types) == (30.0, None)
    assert calc("days_between(t0, t1)", vals, types) == (1.25, None)
    assert calc("year(start)", vals, types, "integer") == (2024, None)
    assert calc("month(start)", vals, types, "integer") == (1, None)
    assert calc("day(start)", vals, types, "integer") == (30, None)
    assert calc("year(season)", vals, types, "integer") == (2019, None)
    assert calc("date_add(start, 2)", vals, types, "date") == ("2024-02-01", None)
    assert calc("date_add(t0, 0.5)", vals, types, "datetime") == (
        "2024-01-01T12:00:00+00:00",
        None,
    )
    # A date known only to the year has no day to count from.
    value, error = calc("days_between(season, end)", vals, types, "integer")
    assert value is None and "full date" in error


def test_a_blank_input_gives_a_blank_result_unless_coalesced():
    assert calc("a + b", {"a": 1}, NUMS) == (None, None)
    assert calc("concat(a, b)", {"a": 1}, NUMS, "string") == (None, None)
    assert calc("coalesce(b, 0) + a", {"a": 1}, NUMS) == (1.0, None)
    assert calc("a > b", {"a": 1, "b": ""}, NUMS, "boolean") == (None, None)


def test_results_are_given_as_their_type():
    assert calc("a / 3", {"a": 1}, NUMS, "float", 2) == (0.33, None)
    assert calc("a / 3", {"a": 5}, NUMS, "integer") == (2, None)
    assert calc("a", {"a": 5}, NUMS, "string") == ("5", None)
    value, error = calc('"x"', {}, {}, "boolean")
    assert value is None and "not yes/no" in error


@pytest.mark.parametrize(
    ("source", "values", "message"),
    [
        ("a / b", {"a": 1, "b": 0}, "divided by zero"),
        ("a % b", {"a": 1, "b": 0}, "divided by zero"),
        ("sqrt(a)", {"a": -1}, "negative"),
        ("log(a)", {"a": 0}, "above zero"),
        ("a ** 2000", {"a": 2}, "at most"),
        ("a ** b", {"a": 10.0, "b": 400}, "too large"),
        ("exp(a)", {"a": 1000}, "too large"),
    ],
)
def test_a_value_that_cant_be_worked_out_is_blank_with_a_reason(
    source, values, message
):
    value, error = calc(source, values, NUMS)
    assert value is None
    assert message in error


def test_wrong_kinds_at_read_time_never_raise():
    value, error = calc("a + b", {"a": "x", "b": 1}, {"a": "string", "b": "float"})
    assert value is None and error


@pytest.mark.parametrize(
    "source",
    [
        '__import__("os")',
        "a.__class__",
        "a.b.c",
        "__builtins__",
        "[x for x in a]",
        "{x: 1 for x in a}",
        "(x for x in a)",
        "lambda: 1",
        "a[0]",
        "open('f')",
        "eval('1')",
        "round(a, ndigits=2)",
        "round(*a)",
        "a if b",
        "x := 1",
        "None",
        "b'bytes'",
        "a in b",
        "a is b",
        "f'{a}'",
        "a.upper()",
        "",
        "a" * (F.MAX_SOURCE + 1),
        "+".join(["a"] * 150),
    ],
)
def test_anything_outside_the_language_is_refused(source):
    with pytest.raises(ValidationError):
        F.parse(source)


def test_text_cant_be_grown_without_bound():
    big = "x" * 6000
    value, error = calc("s + s", {"s": big}, {"s": "string"}, "string")
    assert value is None and "longer than" in error


def test_names_include_link_fields():
    assert F.parse("mass / site.area + mass").names == ("mass", "site.area")


@pytest.mark.parametrize(
    ("source", "kinds", "expected"),
    [
        ("a + 1", {"a": F.NUMBER}, F.NUMBER),
        ("a > 1", {"a": F.NUMBER}, F.BOOL),
        ('concat(s, "x")', {"s": F.TEXT}, F.TEXT),
        ("date_add(d, 1)", {"d": F.DATE}, F.DATE),
        ("coalesce(a, 0)", {"a": F.NUMBER}, F.NUMBER),
        ("days_between(d, d)", {"d": F.DATE}, F.NUMBER),
    ],
)
def test_infer_says_what_comes_out(source, kinds, expected):
    assert F.infer(F.parse(source), kinds) == expected


@pytest.mark.parametrize(
    ("source", "kinds"),
    [
        ("missing + 1", {}),
        ('a + "x"', {"a": F.NUMBER}),
        ("a > s", {"a": F.NUMBER, "s": F.TEXT}),
        ("not a", {"a": F.NUMBER}),
        ("upper(a)", {"a": F.NUMBER}),
        ("year(a)", {"a": F.NUMBER}),
        ("d - d", {"d": F.DATE}),
        ('1 if c else "x"', {"c": F.BOOL}),
        ("round()", {}),
        ("sqrt(1, 2)", {}),
    ],
)
def test_infer_refuses_what_doesnt_fit(source, kinds):
    with pytest.raises(ValidationError):
        F.infer(F.parse(source), kinds)


def test_fits():
    assert F.fits(F.NUMBER, "float") and F.fits(F.NUMBER, "integer")
    assert F.fits(F.NUMBER, "string")
    assert not F.fits(F.TEXT, "float")
    assert F.fits(F.DATETIME, "date") and not F.fits(F.NUMBER, "date")


def test_rename_keeps_everything_else():
    assert F.rename("x + x2 * (x)", "x", "y") == "y + x2 * (y)"
    assert F.rename("site.x + x", "x", "z", via="site") == "site.z + x"
    assert F.rename("site.x + x", "site", "place") == "place.x + x"
    assert F.rename('concat(naïve, "x")', "naïve", "plain") == 'concat(plain, "x")'
    assert F.uses(F.parse("site.area"), "area", via="site")
    assert F.uses(F.parse("site.area"), "site")
    assert not F.uses(F.parse("site.area"), "area")
