"""The data-check report's own rules: what is blank, which blanks a filter can
list, and how findings add up into lines with a few examples each."""

from __future__ import annotations

import pytest

from civex.domain import quality
from civex.domain.exceptions import ValidationError


def test_blank_values():
    assert all(quality.is_blank(v) for v in (None, "", [], {}))
    assert not any(quality.is_blank(v) for v in (0, False, "x", [1]))


def test_a_blank_filter_says_exactly_the_blank_values_where_it_can():
    assert quality.blank_filter("depth", "integer", "sample") == {
        "field": "depth",
        "op": "is_null",
        "schema": "sample",
    }
    text = quality.blank_filter("code", "string", "sample")
    assert text is not None and len(text["or"]) == 2
    # A list's empty value is [], which no filter condition says.
    assert quality.blank_filter("tags", "tags", "sample") is None


def _finding(issue: str, field: str, rid: str) -> quality.Finding:
    return quality.Finding(issue, "sample", field, rid, f"#{rid}", "why")


def test_findings_add_up_per_field_with_a_few_examples():
    tally = quality.Tally()
    tally.kind("sample", "Sample")
    tally.field("sample", "code", "Code", "string", required=True)
    tally.field("sample", "note", "Note", "string", required=False)
    for i in range(8):
        tally.saw("sample")
        tally.add(_finding(quality.BREAKS_RULE, "code", str(i)), "Code")
    tally.add(_finding(quality.BLANK, "note", "1"), "Note")
    tally.add(_finding(quality.BLANK, "code", "9"), "Code")
    report = tally.report()
    (kind,) = report.kinds
    assert kind.records == 8
    # Issues in the order they are declared; a blank in a field that isn't
    # required is a count, not an issue.
    assert [(i.issue, i.field, i.count) for i in kind.issues] == [
        (quality.BREAKS_RULE, "code", 8),
        (quality.BLANK, "code", 1),
    ]
    assert len(kind.issues[0].examples) == quality.MAX_EXAMPLES
    assert {b.field: b.blank for b in kind.blanks} == {"code": 1, "note": 1}
    assert kind.records_with_issues == 9
    assert report.issues == 9


def test_an_unknown_issue_is_refused():
    with pytest.raises(ValidationError):
        quality.check_issue("outlier")
    for name in quality.ISSUES:
        quality.check_issue(name)
