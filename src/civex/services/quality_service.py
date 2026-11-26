"""Data checks: what in the records a query lists needs a look.

`QualityService` walks the records once, a page at a time
(`RecordService.stream_records`, which already says where each file is and
names each record), and asks each value the rules that exist for it:
`restriction_problem` (the field's restrictions, `_check_restrictions`),
`RecordService.reference_problems` (where a reference may point, the rule a
save uses), `RecordRepository.key_duplicates` (a uniqueness key, the rule
`set_unique_keys` refuses on) and `file_access.place_of` (where a file is).
What counts as an issue, and the words for it, are `domain/quality`.

Costs: a page of records is read as any list reads it; the references on a
page are checked together (one lookup, plus each other collection once);
each uniqueness key is one pass over its kind, whatever the page count.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

from civex.domain import permissions, quality
from civex.domain.dtos import DatasetDTO, FieldDTO, RecordDTO, ResolvedSchema
from civex.domain.exceptions import NotFoundError
from civex.domain.file_access import PLACE_MISSING, FileItem, place_of
from civex.domain.permissions import EVERYTHING, Permissions
from civex.domain.query import RecordQuery
from civex.services.record_service import (
    BULK_EDIT_PAGE,
    RecordService,
    restriction_problem,
)
from civex.services.schema_service import SchemaService

_FILE_DTYPES = ("file", "file_list")
_REFERENCE_DTYPES = ("reference", "reference_list")

# One record's findings, as the walk yields them.
_Checked = tuple[RecordDTO, ResolvedSchema, list[quality.Finding]]


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _missing_file(record: RecordDTO, field: str, ref: dict[str, Any]) -> bool:
    """Whether the file `ref` (as a list stamps it with its `location`) is on
    no drive and not on the server: `place_of`'s `missing`, the one rule."""
    location = ref.get("location") or {}
    item = FileItem(
        path="",
        sha256=str(ref.get("sha256") or ""),
        filename=str(ref.get("filename") or ""),
        size=int(ref.get("size") or 0),
        record_id=str(record.id),
        record_name=record.natural_name or "",
        field=field,
        volume=location.get("volume"),
        state=location.get("state") or "unknown",
        available=location.get("available") is True,
    )
    return place_of(item)[0] == PLACE_MISSING


class QualityService:
    def __init__(
        self,
        records: RecordService,
        schemas: SchemaService,
        permissions: Permissions = EVERYTHING,
    ) -> None:
        self._records = records
        self._schemas = schemas
        self._permissions = permissions
        # Whether this copy holds only some of the project's records.
        self.partial: Callable[[], bool] = lambda: False

    # -- the report --------------------------------------------------------

    def check(self, query: RecordQuery) -> quality.QualityReport:
        """What needs a look in the records `query` lists, per kind and field:
        each issue counted, with a few records named (`MAX_EXAMPLES`), and how
        many records leave each field empty."""
        self._permissions.require_somewhere(permissions.READ)
        tally = quality.Tally()
        declared: set[str] = set()
        for record, shape, findings in self._walk(query):
            schema = shape.schema
            if schema.name not in declared:
                declared.add(schema.name)
                tally.kind(schema.name, schema.display_name)
                for f in schema.fields:
                    tally.field(
                        schema.name, f.name, f.display_name, f.dtype, f.required
                    )
            tally.saw(schema.name)
            labels = {f.name: f.display_name for f in schema.fields}
            for finding in findings:
                tally.add(finding, self._label(finding.field, labels))
        return tally.report()

    @staticmethod
    def _label(field: str, labels: dict[str, str]) -> str:
        return ", ".join(labels.get(n, n) for n in field.split(","))

    def records_with(
        self,
        query: RecordQuery,
        issue: str,
        field: str | None = None,
        schema: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[quality.Finding], int]:
        """Exactly the records `query` lists that have `issue` (on `field`, a
        field's name or a key's, and of kind `schema`, when given): one finding
        per record, a page of them, and how many there are. What the report's
        lines open, for a person to look at or tick and edit."""
        self._permissions.require_somewhere(permissions.READ)
        quality.check_issue(issue)
        found: list[quality.Finding] = []
        total = 0
        for record, shape, findings in self._walk(query, issues={issue}):
            if schema and shape.schema.name != schema:
                continue
            match = next(
                (f for f in findings if field is None or f.field == field), None
            )
            if match is None:
                continue
            if offset <= total < offset + limit:
                found.append(match)
            total += 1
        return found, total

    def check_field(
        self,
        schema_name: str,
        field_name: str,
        restrictions: dict[str, Any] | None = None,
        required: bool | None = None,
        deleting: bool = False,
    ) -> quality.FieldCheck:
        """What the values stored for a field make of its rules as they would
        be (`restrictions`, `required`; as they are when left out): how many
        records' values they refuse, how many leave a required field empty,
        and a few of them named. Every collection; nothing is changed. What
        the field editor warns with before a rule is tightened. `deleting`:
        counts the records that hold a value for the field instead (what
        deleting it would take with it). It only warns: nothing here blocks."""
        self._permissions.require_somewhere(permissions.READ)
        schema = self._schemas.get(schema_name)
        field = next((f for f in schema.fields if f.name == field_name), None)
        if field is None:
            raise NotFoundError(
                f"Field '{field_name}' not found on schema '{schema_name}' (a "
                "record holds values only for its kind's own fields)"
            )
        if restrictions is not None:
            self._schemas.check_restrictions(field.dtype, restrictions)
        result = quality.FieldCheck(
            schema=schema.name, field=field.name, partial=self.partial()
        )
        if deleting:
            for page in self._records.stream_records(
                RecordQuery(schema=schema.name), page_size=BULK_EDIT_PAGE
            ):
                for record in page:
                    if quality.is_blank(record.data.get(field.name)):
                        continue
                    result.holding += 1
                    if len(result.examples) < quality.MAX_EXAMPLES:
                        result.examples.append(
                            quality.Example(
                                str(record.id),
                                record.natural_name,
                                "Holds a value that goes with the field",
                            )
                        )
            return result
        wants_blank = field.required if required is None else required
        issues = {quality.BREAKS_RULE} | ({quality.BLANK} if wants_blank else set())
        for _, _, findings in self._walk(
            RecordQuery(schema=schema.name),
            issues=issues,
            only_field=field.id,
            rules={field.id: restrictions} if restrictions is not None else None,
        ):
            for finding in findings:
                if finding.issue == quality.BREAKS_RULE:
                    result.breaks_rule += 1
                else:
                    result.blank += 1
                if len(result.examples) < quality.MAX_EXAMPLES:
                    result.examples.append(
                        quality.Example(
                            finding.record_id, finding.record_name, finding.message
                        )
                    )
        return result

    # -- the walk ----------------------------------------------------------

    def _walk(
        self,
        query: RecordQuery,
        issues: set[str] | None = None,
        only_field: uuid.UUID | None = None,
        rules: dict[uuid.UUID, dict[str, Any] | None] | None = None,
    ) -> Iterator[_Checked]:
        """Every record `query` lists with what is found on it, a page at a
        time: `issues` (None: every kind), on `only_field` (None: every own
        field), with `rules` standing in for some fields' restrictions."""
        wanted = set(quality.ISSUES) if issues is None else issues
        shapes = self._schemas.resolver()
        duplicates: dict[uuid.UUID, dict[uuid.UUID, list[list[str]]]] = {}
        owners: dict[uuid.UUID, DatasetDTO | None] = {}
        for page in self._records.stream_records(query, page_size=BULK_EDIT_PAGE):
            checked: list[_Checked] = []
            links: dict[uuid.UUID, list[tuple[int, str, Any]]] = {}
            for record in page:
                shape = shapes(record.schema_id)
                if shape is None:
                    continue
                findings: list[quality.Finding] = []
                for f in shape.schema.fields:
                    if only_field is not None and f.id != only_field:
                        continue
                    value = record.data.get(f.name)
                    findings.extend(
                        self._value_findings(record, shape, f, value, wanted, rules)
                    )
                    if (
                        quality.BROKEN_REFERENCE in wanted
                        and f.dtype in _REFERENCE_DTYPES
                        and not quality.is_blank(value)
                    ):
                        for item in _items(value):
                            links.setdefault(record.dataset_id, []).append(
                                (len(checked), f.name, item)
                            )
                if quality.DUPLICATE_KEY in wanted and shape.schema.unique_keys:
                    findings.extend(self._duplicates(record, shape, duplicates))
                checked.append((record, shape, findings))
            for dataset_id, items in links.items():
                problems = self._records.reference_problems(
                    [(name, item) for _, name, item in items], dataset_id, owners
                )
                for (i, name, _), problem in zip(items, problems):
                    if problem is None:
                        continue
                    record, shape, findings = checked[i]
                    findings.append(
                        self._finding(
                            quality.BROKEN_REFERENCE, record, shape, name, problem
                        )
                    )
            yield from checked

    def _value_findings(
        self,
        record: RecordDTO,
        shape: ResolvedSchema,
        field: FieldDTO,
        value: Any,
        wanted: set[str],
        rules: dict[uuid.UUID, dict[str, Any] | None] | None,
    ) -> list[quality.Finding]:
        found: list[quality.Finding] = []
        if quality.is_blank(value):
            if quality.BLANK in wanted:
                found.append(
                    self._finding(quality.BLANK, record, shape, field.name, "No value")
                )
            return found
        if quality.BREAKS_RULE in wanted:
            problem = restriction_problem(
                value, field, (rules or {}).get(field.id, field.restrictions)
            )
            if problem:
                found.append(
                    self._finding(
                        quality.BREAKS_RULE, record, shape, field.name, problem
                    )
                )
        if quality.MISSING_FILE in wanted and field.dtype in _FILE_DTYPES:
            for ref in _items(value):
                if isinstance(ref, dict) and _missing_file(record, field.name, ref):
                    found.append(
                        self._finding(
                            quality.MISSING_FILE,
                            record,
                            shape,
                            field.name,
                            f"'{ref.get('filename')}' is on no drive and not on "
                            "the server",
                        )
                    )
        return found

    def _duplicates(
        self,
        record: RecordDTO,
        shape: ResolvedSchema,
        cache: dict[uuid.UUID, dict[uuid.UUID, list[list[str]]]],
    ) -> list[quality.Finding]:
        """The uniqueness keys `record` shares with another live record in its
        place. Each key of a kind is looked for once, in one pass over the
        kind (`key_duplicates`), the first time a record of it is seen."""
        schema = shape.schema
        if schema.id not in cache:
            sharing: dict[uuid.UUID, list[list[str]]] = {}
            for key in schema.unique_keys:
                names = [shape.id_to_name.get(i, i) for i in key]
                for group in self._records.records_repo.key_duplicates(schema.id, key):
                    for rid in group:
                        sharing.setdefault(rid, []).append(names)
            cache[schema.id] = sharing
        found = []
        for names in cache[schema.id].get(record.id, []):
            labels = [
                shape.by_name[n].display_name if n in shape.by_name else n
                for n in names
            ]
            found.append(
                self._finding(
                    quality.DUPLICATE_KEY,
                    record,
                    shape,
                    quality.key_label(names),
                    f"Another {schema.display_name} here has the same "
                    + ", ".join(labels),
                )
            )
        return found

    @staticmethod
    def _finding(
        issue: str, record: RecordDTO, shape: ResolvedSchema, field: str, message: str
    ) -> quality.Finding:
        return quality.Finding(
            issue=issue,
            schema=shape.schema.name,
            field=field,
            record_id=str(record.id),
            record_name=record.natural_name,
            message=message,
        )
