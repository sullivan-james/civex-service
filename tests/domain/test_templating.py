import pytest

from civex.domain import templating as t
from civex.domain.exceptions import ValidationError


def test_plain_variables_and_literals():
    assert t.render("{a}-{b}", {"a": "x", "b": 2}) == "x-2"


def test_escaped_braces():
    assert t.render("{{{a}}}", {"a": "x"}) == "{x}"


@pytest.mark.parametrize("bad", ["{a", "a}", "{1x}", "{a:nope}", "{}"])
def test_malformed_templates_are_rejected(bad):
    with pytest.raises(ValidationError):
        t.parse(bad)


def test_text_operations_chain_left_to_right():
    assert t.render("{a:upper}", {"a": "ab"}) == "AB"
    assert t.render("{a:slug|trunc(5)}", {"a": "Hello World"}) == "hello"


def test_number_formats():
    assert t.render("{n:04}", {"n": 42}) == "0042"
    assert t.render("{n:.2f}", {"n": 3.14159}) == "3.14"
    assert t.render("{n:04}", {"n": "abc"}) == "abc"


def test_date_patterns_degrade_to_the_value_precision():
    assert t.render("{d:YYYY-MM-DD}", {"d": "2019-06-14"}) == "2019-06-14"
    assert t.render("{d:YYYY-MM-DD}", {"d": "2019-06"}) == "2019-06"
    assert t.render("{d:YYYY-MM-DD}", {"d": "2019"}) == "2019"
    assert t.render("{d:YYYYMMDD_HHmm}", {"d": "2019-06-14T08:30:00+00:00"}) == (
        "20190614_0830"
    )


def test_skip_drops_missing_variables_and_their_separator():
    assert t.render("{a} - {b}", {"b": "B"}) == "B"
    assert t.render("{a} - {b}", {"a": "A"}) == "A"
    assert t.render("{a} - {b} - {c}", {"a": "A", "c": "C"}) == "A - C"
    assert t.render("{a} {b}", {"a": "  ", "b": "B"}) == "B"


def test_skip_returns_none_when_nothing_is_left():
    assert t.render("{a} {b}", {"a": None}) is None


def test_fallback_gives_none_when_any_variable_is_missing():
    assert t.render("{a}_{b}", {"a": "x"}, on_missing="fallback") is None


def test_empty_renders_missing_as_nothing():
    assert t.render("{a}_{b}", {"a": "x"}, on_missing="empty") == "x_"


def test_builtins_win_over_fields():
    assert t.render("{id}", {"id": "field"}, {"id": "abc"}) == "abc"


def test_validate_names_unknown_variables():
    t.validate("{a}.{ext}", {"a"}, ("ext",))
    with pytest.raises(ValidationError, match="zzz"):
        t.validate("{a}{zzz}", {"a"})


def test_rename_keeps_formats():
    assert t.rename_field("{a:upper}-{a}-{b}", "a", "c") == "{c:upper}-{c}-{b}"


def test_rename_preserves_escaped_braces():
    assert t.rename_field("{{{a}}}", "a", "b") == "{{{b}}}"


def test_remove_drops_the_variable_and_its_separator():
    assert t.remove_field("{a} - {b}", "b") == "{a}"
    assert t.remove_field("{a} - {b}", "a") == "{b}"
    assert t.remove_field("{a}", "a") == ""


def test_from_field_list():
    assert t.from_field_list(["a", "b"]) == "{a} {b}"


def test_dotted_variables_render_from_resolved_values():
    assert t.render("{site.name}-{n:03}", {"site.name": "Ridge", "n": 4}) == (
        "Ridge-004"
    )
    assert t.render("{site.name} {n}", {"n": 4}) == "4"  # unresolved is skipped


@pytest.mark.parametrize("bad", ["{a.b.c}", "{.b}", "{a.}"])
def test_only_one_hop_is_syntax(bad):
    with pytest.raises(ValidationError):
        t.parse(bad)


def test_validate_dotted_against_reference_targets():
    targets = {"site": {"name", "elevation"}}
    t.validate("{site.name}", {"site"}, (), targets)
    with pytest.raises(ValidationError, match="no field 'ghost'"):
        t.validate("{site.ghost}", {"site"}, (), targets)
    with pytest.raises(ValidationError, match="reference field"):
        t.validate("{other.name}", {"site"}, (), targets)
    with pytest.raises(ValidationError, match="can't be used here"):
        t.validate("{site.name}", {"site"})


def test_rename_and_remove_follow_a_reference_field_itself():
    assert t.rename_field("{site.name}-{n}", "site", "place") == "{place.name}-{n}"
    assert t.remove_field("{site.name} - {n}", "site") == "{n}"


def test_rename_and_remove_a_field_of_the_referenced_schema():
    assert t.rename_field("{site.name}-{name}", "name", "title", via="site") == (
        "{site.title}-{name}"
    )
    assert t.remove_field("{site.name} - {name}", "name", via="site") == "{name}"


def test_longtext_is_not_nameable() -> None:
    assert "longtext" in t.UNNAMEABLE_DTYPES
