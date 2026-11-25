"""Data checks: what in the stored records needs a look (pure).

A check walks the records a query lists and finds, per kind of record and
field, values that would not be accepted now or that point at nothing. Each
kind of issue is named once here, with the words a person reads; what counts
as one is decided by the rules that already exist (a field's restrictions, a
uniqueness key, where a reference may point, where a file is), never by a
second copy of them:

- `breaks_rule`: a stored value the field's *current* restrictions refuse.
  Tightening a rule (a lower `max`, fewer `choices`, a finer `precision`)
  doesn't re-check what is stored, so these are what such a change left.
- `blank`: a field with no value. An issue only where the field is marked
  required; for every other field the count is given as information.
- `duplicate_key`: records sharing a uniqueness key's values in one place.
- `broken_reference`: a link to a record that is deleted, gone, or in a
  local collection the record can't reach.
- `missing_file`: a file whose content is on no drive, here or (when the
  project syncs) on the server.

Not checked: outliers. Telling an unusual number from a usual one needs the
spread of the values (quartiles), which SQLite can't work out without
reading every value, and keeping them all would make a check's memory grow
with the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any

from civex.domain.exceptions import ValidationError

BREAKS_RULE = "breaks_rule"
BLANK = "blank"
DUPLICATE_KEY = "duplicate_key"
BROKEN_REFERENCE = "broken_reference"
MISSING_FILE = "missing_file"


@dataclass(frozen=True)
class IssueKind:
    name: str
    label: str  # a few words, as a heading
    description: str  # one sentence, what it means and why it matters


ISSUES: dict[str, IssueKind] = {
    k.name: k
    for k in (
        IssueKind(
            BREAKS_RULE,
            "Breaks a rule",
            "A stored value the field's rules refuse now, usually because a "
            "rule was tightened after the value was entered. The record can't "
            "be saved again until the value is put right.",
        ),
        IssueKind(
            BLANK,
            "Required but empty",
            "A field marked required that has no value.",
        ),
        IssueKind(
            DUPLICATE_KEY,
            "Shares a unique key",
            "Records in the same place holding the same values for fields "
            "that should be unique together.",
        ),
        IssueKind(
            BROKEN_REFERENCE,
            "Broken link",
            "A link to a record that has been deleted, or that this record "
            "can no longer reach.",
        ),
        IssueKind(
            MISSING_FILE,
            "Missing file",
            "A file whose content is on no drive here and not on the server.",
        ),
    )
}

# How many records each line of a report names (the count is exact).
MAX_EXAMPLES = 5

# Field types whose empty value is "" as well as no value at all, so a filter
# can list exactly the blank ones. A list field's empty value ([]) has no
# filter condition.
_TEXT_DTYPES = frozenset({"string", "longtext", "enum", "url"})


def check_issue(issue: str) -> None:
    if issue not in ISSUES:
        raise ValidationError(
            f"Unknown issue '{issue}'. Use one of: {', '.join(ISSUES)}"
        )


def is_blank(value: Any) -> bool:
    """Whether a stored value is empty: none, "", or an empty list."""
    return value is None or value == "" or value == [] or value == {}


def blank_filter(field_name: str, dtype: str, schema: str) -> dict[str, Any] | None:
    """The filter condition (the explorer's wire shape) listing exactly the
    records of `schema` whose `field_name` is blank, or None when no filter
    says it (a list field, whose empty value is [])."""
    if dtype in ("tags", "file_list", "reference_list", "geo"):
        return None
    null = {"field": field_name, "op": "is_null", "schema": schema}
    if dtype in _TEXT_DTYPES:
        return {
            "or": [
                null,
                {"field": field_name, "op": "eq", "value": "", "schema": schema},
            ]
        }
    return null


def key_label(names: list[str]) -> str:
    """How a uniqueness key is named where a field would be: its fields."""
    return ",".join(names)


@dataclass(frozen=True)
class Finding:
    """One issue on one record: what the walk yields."""

    issue: str
    schema: str  # the kind's name
    field: str  # a field's name, or a key's (`key_label`)
    record_id: str
    record_name: str | None
    message: str


@dataclass
class Example:
    record_id: str
    record_name: str | None
    message: str


@dataclass
class IssueCount:
    """One line of a report: an issue on one field of one kind."""

    issue: str
    field: str
    field_label: str
    count: int = 0
    examples: list[Example] = _field(default_factory=list)
    # Lists exactly these records in the explorer, when a filter can say it.
    filter: dict[str, Any] | None = None

    @property
    def description(self) -> str:
        return ISSUES[self.issue].description


@dataclass
class FieldBlanks:
    """How many records of a kind leave a field empty (information, not an
    issue unless the field is required)."""

    field: str
    field_label: str
    required: bool
    blank: int = 0
    filter: dict[str, Any] | None = None


@dataclass
class KindReport:
    schema: str
    schema_label: str
    records: int = 0
    records_with_issues: int = 0
    issues: list[IssueCount] = _field(default_factory=list)
    blanks: list[FieldBlanks] = _field(default_factory=list)


@dataclass
class QualityReport:
    kinds: list[KindReport] = _field(default_factory=list)

    @property
    def records(self) -> int:
        return sum(k.records for k in self.kinds)

    @property
    def records_with_issues(self) -> int:
        return sum(k.records_with_issues for k in self.kinds)

    @property
    def issues(self) -> int:
        return sum(i.count for k in self.kinds for i in k.issues)


class Tally:
    """Builds a report from what a walk finds, in the order fields are
    declared. The service hands it each record seen (`saw`) and each finding
    (`add`); nothing here reads the database."""

    def __init__(self) -> None:
        self._kinds: dict[str, KindReport] = {}
        self._lines: dict[tuple[str, str, str], IssueCount] = {}
        self._blanks: dict[tuple[str, str], FieldBlanks] = {}
        self._flagged: dict[str, set[str]] = {}

    def kind(self, schema: str, label: str) -> KindReport:
        if schema not in self._kinds:
            self._kinds[schema] = KindReport(schema=schema, schema_label=label)
            self._flagged[schema] = set()
        return self._kinds[schema]

    def field(
        self, schema: str, name: str, label: str, dtype: str, required: bool
    ) -> None:
        """Declare a field of a kind, so its blanks are counted (even when
        none are) and its lines come in the order fields are shown."""
        key = (schema, name)
        if key not in self._blanks:
            line = FieldBlanks(
                field=name,
                field_label=label,
                required=required,
                filter=blank_filter(name, dtype, schema),
            )
            self._blanks[key] = line
            self._kinds[schema].blanks.append(line)

    def saw(self, schema: str) -> None:
        self._kinds[schema].records += 1

    def add(self, finding: Finding, field_label: str) -> None:
        if finding.issue == BLANK:
            blanks = self._blanks.get((finding.schema, finding.field))
            if blanks is not None:
                blanks.blank += 1
                if not blanks.required:
                    return  # information only
        key = (finding.schema, finding.issue, finding.field)
        line = self._lines.get(key)
        if line is None:
            blanks = self._blanks.get((finding.schema, finding.field))
            line = IssueCount(
                issue=finding.issue,
                field=finding.field,
                field_label=field_label,
                filter=blanks.filter if finding.issue == BLANK and blanks else None,
            )
            self._lines[key] = line
            self._kinds[finding.schema].issues.append(line)
        line.count += 1
        if len(line.examples) < MAX_EXAMPLES:
            line.examples.append(
                Example(finding.record_id, finding.record_name, finding.message)
            )
        flagged = self._flagged[finding.schema]
        if finding.record_id not in flagged:
            flagged.add(finding.record_id)
            self._kinds[finding.schema].records_with_issues += 1

    def report(self) -> QualityReport:
        order = list(ISSUES)
        for kind in self._kinds.values():
            kind.issues.sort(key=lambda line: order.index(line.issue))
        return QualityReport(kinds=list(self._kinds.values()))


@dataclass
class FieldCheck:
    """What a field's rules, as they would be, make of the values stored:
    how many records' values they refuse (and, for a required field, how
    many leave it empty). Before a field is changed, so a person is warned."""

    schema: str
    field: str
    breaks_rule: int = 0
    blank: int = 0
    # Deleting the field: how many records hold a value for it.
    holding: int = 0
    # This copy holds only some of the project's records, so the counts are
    # for those: the authority may find more.
    partial: bool = False
    examples: list[Example] = _field(default_factory=list)
