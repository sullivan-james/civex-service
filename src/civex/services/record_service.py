from __future__ import annotations

import dataclasses
from contextlib import AbstractContextManager, nullcontext
import numbers
import re
import uuid
from datetime import date as _date, datetime as _dt, timezone
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Iterator
from zoneinfo import ZoneInfo

from civex.domain.bundle import plain_data
from civex.domain.charts import Chart
from civex.domain.cursor import decode_cursor, encode_cursor
from civex.domain import permissions
from civex.domain.file_refs import collect_sha256_refs
from civex.domain import notes as note_rules
from civex.domain.permissions import EVERYTHING, Permissions
from civex.domain.file_refs import without_file_locations
from civex.domain.file_access import arriving_location
from civex.domain.sync import not_on_server_yet
from civex.domain.dtos import (
    OrphanDTO,
    DERIVED_FILE_KEYS,
    BlockerDTO,
    DatasetDTO,
    FieldDTO,
    FieldValueDTO,
    FileRef,
    BulkEditSkipDTO,
    MissingFileGroupDTO,
    MissingFilesRemovalDTO,
    RecordBulkEditPlanDTO,
    RecordBulkEditResultDTO,
    RecordChangesDTO,
    RecordChangesResultDTO,
    RecordDTO,
    RecordMovePlanDTO,
    RecordMoveResultDTO,
    RecordPoint,
    RecordPoints,
    FormulaPreviewDTO,
    POINTS_DEFAULT_LIMIT,
    POINTS_MAX_LIMIT,
    ReferrerGroupDTO,
    ResolvedField,
    ResolvedSchema,
    RestoreConflictDTO,
    RestorePlanDTO,
    RestoreRow,
    RestoreSetDTO,
    RestoreSetResultDTO,
    SchemaDTO,
)
from civex.domain import filename_extract
from civex.domain import geo as geo_domain
from civex.domain.audit_diff import tombstone
from civex.domain import formulas, partial_dates, templating, units
from civex.domain.field_descriptors import COMPUTED_DTYPES
from civex.domain.exceptions import (
    FieldValueError,
    CoercionError,
    DuplicateRecordError,
    NotFoundError,
    ValidationError,
)
from civex.domain.filters import (
    SELF,
    FilterCondition,
    FilterNode,
    Relation,
    SortKey,
    leaves,
    map_leaves,
    parse_filter_tree,
)
from civex.domain.query import (
    META_SORTS,
    UNSEARCHED_DTYPES,
    RecordQuery,
    RecordSet,
    ResolvedQuery,
    ResolvedSet,
    TextSearch,
)
from civex.domain.file_access import HeldFile, record_key
from civex.domain.scopes import GLOBAL, can_reference
from civex.domain import summary
from civex.domain.timezones import offset_changes, parse_datetime
from civex.domain.uniqueness import key_values
from civex.repositories.protocols import (
    RecordPlace,
    AuditRepository,
    DatasetRepository,
    ObjectStore,
    RecordRepository,
)
from civex.services.progress import Progress
from civex.services.schema_service import SchemaResolver, SchemaService

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from civex.services.workflow_job_service import WorkflowJobService


# Records per page when a bulk operation walks a whole result set.
EXPORT_PAGE = 500


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _parse_date(v: str) -> str:
    """A year, month or day, kept at the precision it was written at."""
    return partial_dates.normalise(v)


def _parse_datetime(v: str, tz: str | None = None) -> str:
    """Normalise to a UTC ISO string; offset-less input is read in *tz*
    (UTC when None). See civex.domain.timezones."""
    return parse_datetime(v, tz)


_COERCE: dict[str, Any] = {
    "integer": int,
    "float": float,
    "string": str,
    "boolean": lambda v: (
        v.strip().lower() in ("true", "yes", "1") if isinstance(v, str) else bool(v)
    ),
    "date": _parse_date,
    "datetime": _parse_datetime,
    "enum": str,
    "url": str,
    "longtext": str,
    "tags": lambda v: (
        [t.strip() for t in v.split(",")] if isinstance(v, str) else [str(t) for t in v]
    ),
}


def _file_refs_of(value: Any, dtype: str, field_name: str) -> list[dict[str, Any]]:
    """The file references in a `file` or `file_list` value, refusing any other
    shape: a `file` holds one reference, a `file_list` a list of them, and a
    reference is an object naming its content by `sha256`. A single reference
    in a `file_list` field (or a list in a `file` field) would be stored as it
    came and break everything that reads the field."""
    if dtype == "file_list":
        if not isinstance(value, list):
            raise ValidationError(
                f"Field '{field_name}' holds a list of files, but was given "
                f"{_shape_word(value)}"
            )
        refs = value
    else:
        if isinstance(value, list):
            raise ValidationError(
                f"Field '{field_name}' holds one file, but was given a list"
            )
        refs = [value]
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("sha256"), str):
            raise ValidationError(
                f"Field '{field_name}': {_shape_word(ref)} is not a stored file"
            )
    return refs


def _shape_word(value: Any) -> str:
    if isinstance(value, dict):
        return "a single file" if "sha256" in value else "an object"
    if isinstance(value, list):
        return "a list"
    return f"the value {value!r}"


def _check_restrictions(
    value: Any, dtype: str, restrictions: dict[str, Any], field_name: str
) -> None:
    """Raise ValidationError if value violates field restrictions. Single source of truth."""
    if value is None:
        return

    # URL format is always validated regardless of restrictions.
    if dtype == "url":
        s = str(value)
        if not (s.startswith("http://") or s.startswith("https://")):
            raise ValidationError(
                f"Field '{field_name}': '{value}' is not a valid URL (must start with http:// or https://)"
            )
        return

    if dtype == "geo":
        try:
            geo_domain.check(value, restrictions or {})
        except ValidationError as e:
            raise ValidationError(f"Field '{field_name}': {e}") from None
        return

    if dtype == "date" and isinstance(value, str):
        # Fields without a `precision` take full dates only, as they always have.
        try:
            partial_dates.precision_of(value)
        except ValueError:
            pass  # not date-shaped; left to the caller as before
        else:
            try:
                partial_dates.check_precision(
                    value, (restrictions or {}).get("precision", "day")
                )
            except ValidationError as e:
                raise ValidationError(f"Field '{field_name}': {e}") from None

    if dtype in ("file", "file_list"):
        # The shape is checked whatever the restrictions, like a geometry's.
        _file_refs_of(value, dtype, field_name)

    if dtype in ("integer", "float"):
        # Checked whatever the restrictions: a field with none once stored
        # any value at all. A whole float (2.0, as pandas reads an integer
        # column with gaps) is a whole number.
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise ValidationError(f"Field '{field_name}': '{value}' is not a number")
        if dtype == "integer" and not float(value).is_integer():
            raise ValidationError(
                f"Field '{field_name}': {value} is not a whole number"
            )

    if not restrictions:
        return

    if dtype in ("integer", "float"):
        mn = restrictions.get("min")
        mx = restrictions.get("max")
        if mn is not None and value < mn:
            raise ValidationError(
                f"Field '{field_name}': {value} is below minimum ({mn})"
            )
        if mx is not None and value > mx:
            raise ValidationError(
                f"Field '{field_name}': {value} exceeds maximum ({mx})"
            )

    elif dtype == "string":
        choices = restrictions.get("choices")
        max_length = restrictions.get("max_length")
        if choices is not None and value not in choices:
            raise ValidationError(
                f"Field '{field_name}': '{value}' must be one of: {', '.join(str(c) for c in choices)}"
            )
        if max_length is not None and len(value) > int(max_length):
            raise ValidationError(
                f"Field '{field_name}': value length {len(value)} exceeds max_length {max_length}"
            )

    elif dtype == "longtext":
        max_length = restrictions.get("max_length")
        if max_length is not None and len(value) > int(max_length):
            raise ValidationError(
                f"Field '{field_name}': value length {len(value)} exceeds max_length {max_length}"
            )

    elif dtype == "enum":
        choices = restrictions.get("choices")
        if choices is not None and value not in choices:
            raise ValidationError(
                f"Field '{field_name}': '{value}' must be one of: {', '.join(str(c) for c in choices)}"
            )

    elif dtype == "date" and isinstance(value, str):
        try:
            problem = partial_dates.check_bounds(
                value, restrictions.get("min"), restrictions.get("max")
            )
        except ValueError:
            problem = None  # malformed value or bound; see the datetime branch
        if problem:
            raise ValidationError(f"Field '{field_name}': {problem}")

    elif dtype in ("date", "datetime"):
        mn = restrictions.get("min")
        mx = restrictions.get("max")
        # Compare via parsed objects so timezone offsets don't cause lexicographic bugs.
        try:
            if dtype == "date":
                v_cmp = _date.fromisoformat(str(value))
                mn_cmp = _date.fromisoformat(str(mn)) if mn is not None else None
                mx_cmp = _date.fromisoformat(str(mx)) if mx is not None else None
            else:
                v_cmp = _dt.fromisoformat(str(value))
                mn_cmp = _dt.fromisoformat(str(mn)) if mn is not None else None
                mx_cmp = _dt.fromisoformat(str(mx)) if mx is not None else None
            if mn_cmp is not None and v_cmp < mn_cmp:
                raise ValidationError(
                    f"Field '{field_name}': {value} is before minimum ({mn})"
                )
            if mx_cmp is not None and v_cmp > mx_cmp:
                raise ValidationError(
                    f"Field '{field_name}': {value} is after maximum ({mx})"
                )
        except (ValueError, TypeError):
            pass  # malformed restriction — let it through; the value was already normalised

    elif dtype in ("file", "file_list"):
        refs = value if isinstance(value, list) else [value]  # checked above
        accept = restrictions.get("accept")
        max_size = restrictions.get("max_size")
        allowed_exts = (
            {
                e.strip().lower().lstrip(".")
                for e in accept.split(",")
                if e.strip().startswith(".")
            }
            if accept
            else set()
        )
        for ref in refs:
            if allowed_exts:
                ext = Path(ref.get("filename", "")).suffix.lstrip(".").lower()
                if ext not in allowed_exts:
                    raise ValidationError(
                        f"Field '{field_name}': '{ref.get('filename')}' type '.{ext}' not allowed"
                        f" — accepted: {accept}"
                    )
            if max_size is not None and ref.get("size", 0) > int(max_size):
                raise ValidationError(
                    f"Field '{field_name}': file size {ref.get('size', 0)} bytes"
                    f" exceeds max_size {max_size}"
                )


def restriction_problem(
    value: Any, field: FieldDTO, restrictions: dict[str, Any] | None = None
) -> str | None:
    """Why `field`'s rules (or `restrictions`, rules it would have) refuse a
    stored value, or None: `_check_restrictions` asked without raising, for
    the data check, which reports every value instead of stopping at one."""
    try:
        _check_restrictions(
            value,
            field.dtype,
            field.restrictions if restrictions is None else restrictions,
            field.name,
        )
    except ValidationError as e:
        return str(e)
    return None


# Path separators and characters invalid in filenames on common filesystems —
# template values come from user-entered field data, so they're untrusted.
_UNSAFE_FILENAME_CHARS_RE = re.compile(r'[\\/\x00-\x1f:*?"<>|]')


def resolve_filename(
    ref: FileRef,
    template: str | None,
    field_values: dict[str, Any],
    builtins: dict[str, Any] | None = None,
) -> str:
    """Resolve a `filename_template` restriction against a record's
    (name-keyed) field values, plus those of the records above it and the ones
    its references point at (`ref.field`), when the caller supplies them.

    The template names the stem; the file's own extension is always added. A
    blank value is skipped with the separator beside it, as in a record's name;
    only when nothing at all is left does the file keep its original name.
    `builtins` supplies `schema` and `id`.
    """
    if not template:
        return ref.filename
    # A template saved before the extension was added for you may still use
    # `{ext}` in the middle; it keeps rendering.
    ext = Path(ref.filename).suffix.lstrip(".")
    try:
        stem = templating.render(
            templating.file_stem_template(template),
            field_values,
            {**(builtins or {}), "ext": ext},
            "skip",
        )
    except ValidationError:
        return ref.filename  # a template stored before the rules tightened
    stem = _UNSAFE_FILENAME_CHARS_RE.sub("_", stem or "").strip().rstrip(". ")
    if not stem:
        return ref.filename
    return templating.with_extension(stem, ref.filename)


def _check_open_notes_leaf(leaf: FilterCondition) -> None:
    """A filter condition on whether a record has open threads of notes
    (`civex.domain.notes.OPEN_NOTES_FILTER`): about the listed record itself,
    `eq` true or false."""
    if leaf.schema:
        raise ValidationError(f"'{leaf.field}' is about the listed records only")
    if leaf.op not in note_rules.FILTER_OPERATORS:
        raise ValidationError(
            f"'{leaf.field}' can't be filtered with '{leaf.op}' "
            f"(use {', '.join(note_rules.FILTER_OPERATORS)})"
        )
    if not isinstance(leaf.value, bool):
        raise ValidationError(f"'{leaf.field}' is true or false")


def _audit_batch(audit: AuditRepository | None, kind: str, many: bool):
    """One batch for an operation that touches several records, so history
    shows it as one event. A single record is just its own entry."""
    return audit.batch(kind) if audit is not None and many else nullcontext()


# Records deleted, and their history written, per statement.
_APPLY_CHUNK = 5000
# Records read and saved at a time by a bulk edit.
BULK_EDIT_PAGE = 500
# How many skipped records a bulk change names (the count is exact).
MAX_REPORTED = 200


def _cites(value: Any, shas: set[str]) -> bool:
    return isinstance(value, dict) and value.get("sha256") in shas


def _cited_among(value: Any, shas: set[str]) -> set[str]:
    """Which of `shas` a file or file-list value cites."""
    if isinstance(value, dict):
        return {value["sha256"]} if _cites(value, shas) else set()
    if isinstance(value, list):
        return {v["sha256"] for v in value if _cites(v, shas)}
    return set()


# Field types a save keeps a catalog for (which record holds which file, which
# record links to which): a change to one is saved by itself, so the catalogs
# are kept as any save keeps them.
_CATALOGUED_DTYPES = frozenset({"file", "file_list", "reference", "reference_list"})


def _as_uuid(raw: Any) -> uuid.UUID:
    """An id as the database gave it (text on SQLite), as an id."""
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


def _bulk_edit_problem(shape: ResolvedSchema | None, fields: list[str]) -> str | None:
    """Why a record of `shape` can't take a bulk edit of `fields`, or None. A
    record holds values only for its schema's *own* fields: an inherited one's
    value is on the record above, so it is that kind that is edited."""
    if shape is None:
        return "Its schema no longer exists"
    own = {f.name for f in shape.schema.fields}
    kind = shape.schema.display_name
    for name in fields:
        found = shape.by_name.get(name)
        if found is not None and found.dtype in COMPUTED_DTYPES:
            return f"'{name}' is a formula: it is worked out, never set"
        if name in own:
            continue
        if name in shape.by_name:
            source = next(
                (rf.source_schema_name for rf in shape.fields if rf.field.name == name),
                "the record above",
            )
            return (
                f"'{name}' is a field of the {source} a {kind} sits in, not of "
                f"the {kind} itself: edit the {source} records instead"
            )
        return f"A {kind} has no field '{name}'"
    return None


def _patched(existing: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    """The whole data a record holding `existing` (by field name) would hold
    with only `fields` changed, or None when they already hold those values:
    the one "change only these fields" rule, behind `patch` and a bulk edit.
    A field set to None is cleared; one already empty counts as holding it."""
    if all(existing.get(k) == v for k, v in fields.items()):
        return None
    return {**existing, **fields}


def _is_blank_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _file_dicts(value: Any) -> list[dict[str, Any]]:
    """The file reference dicts in a `file` or `file_list` value."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _changed_values(
    data: dict[str, Any], stored: dict[str, Any] | None
) -> dict[str, Any]:
    """The values in `data` (by field name) that differ from `stored`, the
    record's values now, or all of them when there is none (a create). The
    one rule for what an update checks: a value the record already holds is
    not checked again against restrictions, references or unique keys, so a
    rule tightened since it was stored never blocks an edit to another field.
    Compare after `_strip_derived_file_keys` and `_normalise_datetimes`, so an
    echoed-back file or datetime counts as unchanged."""
    if stored is None:
        return data
    return {k: v for k, v in data.items() if k not in stored or stored[k] != v}


def _strip_derived_file_keys(
    data: dict[str, Any], fields: list[ResolvedField]
) -> dict[str, Any]:
    """`data` without what reads add and a client may echo back: the
    response-only keys on its file values, and any value for a formula
    (worked out when read, never stored)."""

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: v for k, v in item.items() if k not in DERIVED_FILE_KEYS}
        return item

    result = dict(data)
    for rf in fields:
        if rf.field.dtype in COMPUTED_DTYPES:
            result.pop(rf.field.name, None)
            continue
        if rf.field.dtype not in ("file", "file_list"):
            continue
        value = result.get(rf.field.name)
        if isinstance(value, list):
            result[rf.field.name] = [clean(item) for item in value]
        elif isinstance(value, dict):
            result[rf.field.name] = clean(value)
    return result


def _with_resolved_filename(
    ref_dict: dict[str, Any],
    template: str | None,
    field_values: dict[str, Any],
    builtins: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = resolve_filename(
        FileRef.from_dict(ref_dict), template, field_values, builtins
    )
    return {**ref_dict, "resolved_filename": resolved}


# Guardrails for GET /records/{id}/files.zip -- file_list has no built-in
# count restriction (schema_service.VALID_RESTRICTION_KEYS), so without a
# cap here a single record could demand an unboundedly large in-memory zip.
MAX_ZIP_FILE_COUNT = 2000
_MAX_TRAIL_DEPTH = 64  # a record's ancestors; a guard against a parent loop
MAX_ZIP_TOTAL_SIZE = 500 * 1024 * 1024  # 500 MB, summed from stored FileRef.size


def _hashable(value: Any) -> Any:
    """A key value as `find_key_match` compares it (1 == 1.0, a bool is no number)."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _join_names(names: list[str], cap: bool = False) -> str:
    text = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return text[:1].upper() + text[1:] if cap else text


def _unique_zip_name(name: str, used: set[str]) -> str:
    """Append a numeric suffix on collision so files that resolve to the same
    name (e.g. two files on one record, or an under-specific filename_template)
    don't silently overwrite each other as zip entries."""
    if name not in used:
        used.add(name)
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        candidate = f"{stem} ({n}){suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1


def _outside_columns(template: str | None, own: set[str]) -> list[str]:
    """The values a file name template needs that the record's own data can't
    answer: fields inherited from a record above it, and `ref.field` joins.
    Built-ins and a malformed template need nothing."""
    if not template:
        return []
    try:
        names = templating.referenced_names(templating.file_stem_template(template))
    except ValidationError:
        return []
    return [
        n
        for n in names
        if n not in own and n not in templating.BUILTINS_FILE + ("ext",)
    ]


def _apply_filename_templates(
    data: dict[str, Any],
    fields: list[ResolvedField],
    builtins: dict[str, Any] | None = None,
    *,
    own: set[str] | None = None,
    relatives: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Annotate every file/file_list value in `data` with `resolved_filename`,
    derived from that field's `filename_template` restriction (if any).

    With `own` (the schema's own field names) and no `relatives`, a template
    that needs values from other records is left alone: the batch pass that
    fetches them (`_name_files_from_relatives`) names those files. With
    `relatives`, only those templates are filled, from them."""
    values = {**data, **(relatives or {})}
    result = dict(data)
    for rf in fields:
        f = rf.field
        if f.dtype not in ("file", "file_list"):
            continue
        template = (f.restrictions or {}).get("filename_template")
        if own is not None:
            needs_others = bool(_outside_columns(template, own))
            if needs_others != (relatives is not None):
                continue
        value = result.get(f.name)
        if isinstance(value, dict):
            result[f.name] = _with_resolved_filename(value, template, values, builtins)
        elif isinstance(value, list):
            result[f.name] = [
                _with_resolved_filename(item, template, values, builtins)
                if isinstance(item, dict)
                else item
                for item in value
            ]
    return result


def _own_names(shape: ResolvedSchema) -> set[str]:
    """The fields a record of `shape` holds itself (not inherited ones, which
    live on the record above it)."""
    return {
        rf.field.name
        for rf in shape.fields
        if rf.source_schema_name == shape.schema.name
    }


def _name_builtins(schema_name: str, record_id: Any) -> dict[str, Any]:
    """The `{schema}` and `{id}` variables templates can use."""
    return {"schema": schema_name, "id": str(record_id)[:8]}


def _natural_name(
    data: dict[str, Any],
    fields: list,
    display_template: str | None = None,
    builtins: dict[str, Any] | None = None,
) -> str | None:
    """A record's name: its schema's template rendered over its values, else
    the first plain value on the record."""
    if display_template:
        try:
            return templating.render(display_template, data, builtins)
        except ValidationError:
            return None  # a template stored before the rules tightened
    for rf in fields:
        f = rf.field
        if f.dtype in templating.UNNAMEABLE_DTYPES:
            continue
        val = data.get(f.name)
        if val is not None and str(val).strip():
            return str(val)
    return None


def _referrers_message(referrers: list[tuple[RecordDTO, dict[str, str]]]) -> str:
    shown = referrers[:10]
    parts = [
        f"{rec.schema_name} record {rec.id} (via {', '.join(sorted(set(fields.values())))})"
        for rec, fields in shown
    ]
    msg = (
        f"Cannot delete: still referenced by {len(referrers)} record(s): "
        + "; ".join(parts)
    )
    if len(referrers) > len(shown):
        msg += f" and {len(referrers) - len(shown)} more"
    return msg


@dataclasses.dataclass(frozen=True)
class RecordPage:
    """One keyset page of records and the cursor for the next (None when
    this is the last)."""

    items: list[RecordDTO]
    next_cursor: str | None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _key_mark(
    dataset_id: uuid.UUID,
    schema_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    key: list[str],
    values: list[Any],
) -> tuple[Any, ...]:
    """A uniqueness key's place and values, as one comparable thing. The
    database reads a value as the kind it is compared with (a text "30" is a
    stored 30, "true" a stored true), so anything that reads as a number is
    its float and booleans are true/false: two values that could be one there
    are one here (too many alike is only slower)."""
    return (dataset_id, schema_id, parent_id, tuple(key), tuple(map(_canon, values)))


def _canon(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return repr(float(value))
    text_ = str(value)
    try:
        return repr(float(text_))
    except ValueError:
        return text_.lower() if text_.lower() in ("true", "false") else text_


class IncomingCache:
    """What a run of `RecordService.check_incoming` has read: schemas (resolved
    once each) and collections, and, where `use_records` is set, the records it
    asks about (`RecordService.prefetch_incoming`) and which uniqueness keys no
    stored record holds."""

    def __init__(self, resolver: Callable[[], Callable[[uuid.UUID], Any]]) -> None:
        self._resolver = resolver
        self.shapes = resolver()
        self.datasets: dict[uuid.UUID, Any] = {}
        # Whether records may be answered from here: not for a caller who sees
        # only some collections (what it finds is its own view of them).
        self.use_records = False
        # Record id -> where it is (None: not there), for every record the
        # run names: read at once, and kept up with what the run writes.
        self.places: dict[uuid.UUID, RecordPlace | None] = {}
        # Uniqueness keys (see `RecordService.unique_marks`) that no stored
        # record held when they were read, and those the run has since made.
        self.free: set[tuple[Any, ...]] = set()
        self.made: set[tuple[Any, ...]] = set()
        # Records were changed since `places` was read: to be read again.
        self.stale = True

    def clear(self) -> None:
        """Forget what was read (a schema or a collection may have changed)."""
        self.shapes = self._resolver()
        self.datasets.clear()
        self.clear_records()

    def clear_records(self) -> None:
        """Forget the records (and keys) read: something wrote some."""
        self.places.clear()
        self.free.clear()
        self.made.clear()
        self.stale = True


class RecordService:
    def __init__(
        self,
        schema_svc: SchemaService,
        dataset_repo: DatasetRepository,
        record_repo: RecordRepository,
        file_store: ObjectStore,
        job_svc: WorkflowJobService | None = None,
        audit_repo: AuditRepository | None = None,
        permissions: Permissions = EVERYTHING,
    ) -> None:
        # What the caller may do, asked per collection before a record is
        # made, changed, restored or deleted (`domain.permissions`).
        self._permissions = permissions
        self._schema_svc = schema_svc
        self._datasets = dataset_repo
        self._records = record_repo
        self._files = file_store
        # This project follows an authority, so a file its records cite that no
        # drive here holds can be fetched from it (set by `build_local_context`).
        self.files_from_server: Callable[[], bool] = lambda: False
        # Of these files, those the authority hasn't said it holds (set by
        # `context.py`; nothing when the project follows no authority).
        self.not_on_server: Callable[[set[str]], set[str]] = lambda _: set()
        # Of these (record -> files it cites), the pairs a device sent lately
        # (an authority only): such a file on no drive is `arriving`, its
        # device still uploading.
        self.recently_received: Callable[
            [dict[uuid.UUID, set[str]]], set[tuple[uuid.UUID, str]]
        ] = lambda _: set()
        # Of these files, those the authority said it hasn't got, and (reason,
        # fix) for one neither here nor there (set by `context.py`).
        self.server_lacks: Callable[[set[str]], set[str]] = lambda _: set()
        self.why_not_here: Callable[[list[str]], dict[str, tuple[str, str]]] = (
            lambda _: {}
        )
        self._job_svc = job_svc
        self._audit = audit_repo
        # Whether the caller may be given this content (set by `context.py` for
        # one who cannot read every collection; always, for one who can): a save
        # may cite only a file it could download, or it would hand them one.
        self.readable: Callable[[str], bool] = lambda _sha: True
        # Whether a save may cite this file: it must be one the caller could
        # download (so a hash only hidden records hold is refused) and one that
        # is here (so an unknown hash is refused in the same words). Set by
        # `context.py` for one who cannot read every collection.
        self.may_cite: Callable[[str], bool] = lambda _sha: True
        # Runs a block as the caller sees the project, even inside work that
        # otherwise sees all of it (set by `context.py` for one who cannot read
        # every collection): what a pushed record may point at or sit under is
        # checked as the caller would find it, so a hidden record is as absent
        # as one that never was, in the same words.
        self.as_caller: Callable[[], AbstractContextManager[None]] = nullcontext

    def _check_file_rights(
        self, dataset_id: uuid.UUID, before: dict[str, Any], after: dict[str, Any]
    ) -> None:
        """A save that cites a file the record did not hold takes `ADD_FILES`
        in its collection, and one that lets go of a file it held takes
        `DELETE_FILES` (`domain.permissions`): the same two rights whoever
        saves, a person or a device."""
        held = collect_sha256_refs(before)
        wanted = collect_sha256_refs(after)
        if wanted - held:
            self._permissions.require(permissions.ADD_FILES, dataset_id)
            # Citing a file makes it the record's own, so readable by whoever
            # reads the record: a hash only collections the caller cannot read
            # use may not be cited (the same answer for any file).
            for sha in sorted(wanted - held):
                if not self.may_cite(sha):
                    raise ValidationError(permissions.FILE_UNAVAILABLE)
        if held - wanted:
            self._permissions.require(permissions.DELETE_FILES, dataset_id)

    def _require_each(self, action: str, records: Iterable[Any]) -> None:
        """`action` in every collection these records are in, before any of
        them is touched: all or none."""
        for dataset_id in {r.dataset_id for r in records}:
            self._permissions.require(action, dataset_id)

    # ------------------------------------------------------------------
    # Field ID translation (name-keyed ↔ UUID-keyed record data)
    # ------------------------------------------------------------------

    def _names_to_ids(
        self, data: dict[str, Any], shape: ResolvedSchema | None
    ) -> dict[str, Any]:
        if shape is None:
            return data
        return {shape.name_to_id.get(k, k): v for k, v in data.items()}

    def _ids_to_names(
        self, data: dict[str, Any], shape: ResolvedSchema | None
    ) -> dict[str, Any]:
        if shape is None:
            return data
        # A record's data is the values of the fields its kind has. A deleted
        # field's value stays in the stored data (so a restore brings it back)
        # but isn't one of them. Nor is a value left under a key that names no
        # field at all: the id of a field that is gone for good (its kind was
        # purged, or the record's kind no longer sits under the one that had
        # it), or a name kept from before values were stored by field id whose
        # field has since gone. Passed through, it would read as a field no
        # kind has, and a bundle or a release of the record could not be read
        # back ("A line of records.jsonl can't be read").
        return {
            shape.id_to_name.get(k, k): v
            for k, v in data.items()
            if k in shape.id_to_name or k in shape.name_to_id
        }

    def _snapshot(self, dto: RecordDTO) -> dict[str, Any]:
        """What a history entry stores for a record: the record as it is held,
        its values keyed by field *id*. Names change, ids don't, so an entry
        still means the same thing after a field is renamed; `AuditService`
        turns ids into current names when it serves one."""
        return dto.to_dict()

    def _with_names(
        self, dto: RecordDTO, shapes: SchemaResolver | None = None
    ) -> RecordDTO:
        """`dto` with name-keyed data and its natural name. Pass the
        operation's `shapes` when naming several records, so each schema is
        resolved once, not once per record."""
        shape = (shapes or self._schema_svc.resolver())(dto.schema_id)
        if shape is None:
            return dataclasses.replace(dto)
        named_data = self._ids_to_names(dto.data, shape)
        deleted = [
            {
                "id": str(d.field.id),
                "name": d.field.name,
                "label": d.field.display_name,
                "dtype": d.field.dtype,
                "schema_name": d.schema_name,
                "deleted_at": d.field.deleted_at.isoformat()
                if d.field.deleted_at
                else None,
                "value": dto.data[fid],
            }
            for fid, d in shape.deleted_by_id.items()
            if fid in dto.data and not _is_blank_value(dto.data[fid])
        ]
        builtins = _name_builtins(shape.schema.name, dto.id)
        natural_name = _natural_name(
            named_data, shape.fields, shape.schema.display_template, builtins
        )
        named_data = _apply_filename_templates(
            named_data, shape.fields, builtins, own=_own_names(shape)
        )
        return dataclasses.replace(
            dto,
            data=named_data,
            natural_name=natural_name,
            deleted_fields=deleted or None,
        )

    def labels(self, record_ids: list[str]) -> list[RecordDTO]:
        """Each of these records with its name as it is now, for showing a record
        wherever only its id was kept (a run's records, a pin, a link).

        The one place a name is worked out for an id: the same rendering as every
        list and table (the schema's template, `{ref.field}` included), so a
        rename or a template change shows everywhere at once and no name needs to
        be copied into history. Ids that aren't records, and records that no
        longer exist, are left out; a deleted-but-restorable record is returned
        with `deleted_at` set. A fixed number of queries however many ids.
        """
        ids: list[uuid.UUID] = []
        for raw in dict.fromkeys(record_ids):
            try:
                ids.append(uuid.UUID(raw))
            except (ValueError, AttributeError, TypeError):
                continue
        shapes = self._schema_svc.resolver()
        named = [self._with_names(r, shapes) for r in self._records.list_by_ids(ids)]
        return self._label_references(named, shapes)

    def _with_names_many(self, dtos: list[RecordDTO]) -> list[RecordDTO]:
        shapes = self._schema_svc.resolver()
        return [self._with_names(r, shapes) for r in dtos]

    def _attach_reference_labels(
        self, records: list[RecordDTO], shapes: SchemaResolver | None = None
    ) -> list[RecordDTO]:
        """The response-only extras every API read gets: reference labels and
        collection names (`_label_references`), and where each file is stored
        (`_attach_file_locations`). Audit snapshots use `_with_names` alone, so
        none of this -- all of it momentary -- is ever frozen into the log."""
        shapes = shapes or self._schema_svc.resolver()
        return self._attach_formulas(
            self._attach_file_locations(
                self._label_references(
                    self._name_files_from_relatives(records, shapes), shapes
                ),
                shapes,
            ),
            shapes,
        )

    def _attach_open_notes(self, records: list[RecordDTO]) -> list[RecordDTO]:
        """How many threads of notes not yet resolved each record has, and the
        first line of the latest, in one query: on a record read (`get`) and a
        list (`query_records`), not on a write."""
        if not records:
            return records
        found = self._records.open_notes_of([r.id for r in records])
        return [
            dataclasses.replace(
                r,
                open_notes=found[r.id][0] if r.id in found else 0,
                latest_note=note_rules.first_line(found[r.id][1])
                if r.id in found
                else None,
            )
            for r in records
        ]

    def _attach_formulas(
        self, records: list[RecordDTO], shapes: SchemaResolver
    ) -> list[RecordDTO]:
        """Each record's own formula fields worked out, in `derived` (never in
        `data`, so nothing that stores or sends a record's values can carry
        one), with `formula_errors` saying why one is blank when it can't be.
        Per schema, the values it reads from the records above and through
        links are fetched in one batch (`_derived_values`); a schema with no
        formulas costs nothing."""
        groups: dict[uuid.UUID, list[int]] = {}
        for i, r in enumerate(records):
            shape = shapes(r.schema_id)
            if shape is not None and any(
                f.dtype in COMPUTED_DTYPES for f in shape.schema.fields
            ):
                groups.setdefault(r.schema_id, []).append(i)
        if not groups:
            return records
        out = list(records)
        for schema_id, indexes in groups.items():
            shape = shapes(schema_id)
            assert shape is not None
            names = [f.name for f in shape.schema.fields if f.dtype in COMPUTED_DTYPES]
            results = self._formula_results(
                shape.schema, [records[i] for i in indexes], names
            )
            for i, found in zip(indexes, results):
                r = records[i]
                errors = {n: e for n, (_, e) in found.items() if e}
                out[i] = dataclasses.replace(
                    r,
                    derived={
                        **(r.derived or {}),
                        **{n: v for n, (v, _) in found.items()},
                    },
                    formula_errors=errors or None,
                )
        return out

    def _formula_results(
        self, schema: SchemaDTO, records: list[RecordDTO], names: list[str]
    ) -> list[dict[str, tuple[Any, str | None]]]:
        """Per record (all of `schema`, name-keyed), each of the formula fields
        `names` worked out: (value, None), or (None, why) when it can't be.
        The one place a formula is worked out for records. A formula may read
        another of the schema's formulas (worked out first), a field of a
        record above (its formula too) or `link.field`; those are fetched for
        the whole batch, one lookup per level, never per record."""
        own = {f.name: f for f in schema.fields}
        compiled: dict[str, tuple[formulas.Formula | None, str | None]] = {}
        pending = list(names)
        while pending:
            name = pending.pop()
            f = own.get(name)
            if name in compiled or f is None or f.dtype not in COMPUTED_DTYPES:
                continue
            try:
                formula = formulas.parse((f.restrictions or {}).get("expression", ""))
            except ValidationError as e:
                compiled[name] = (None, str(e))
                continue
            compiled[name] = (formula, None)
            pending.extend(n for n in formula.names if n in own)
        outside = list(
            dict.fromkeys(
                n
                for formula, _ in compiled.values()
                if formula is not None
                for n in formula.names
                if n not in own
            )
        )
        extra = (
            self._derived_values(schema.name, records, outside)
            if outside and records
            else [{} for _ in records]
        )
        _, dtypes = self._schema_svc.formula_kinds(schema)

        out: list[dict[str, tuple[Any, str | None]]] = []
        for record, more in zip(records, extra):
            values = {**record.data, **more}
            done: dict[str, tuple[Any, str | None]] = {}

            def work(name: str, seen: frozenset[str]) -> None:
                formula, problem = compiled[name]
                if formula is None:
                    done[name] = (None, problem)
                    return
                if name in seen:
                    done[name] = (None, "it reads itself through other formulas")
                    return
                for used in formula.names:
                    if used in compiled and used not in done:
                        work(used, seen | {name})
                    if used in compiled:
                        values[used] = done[used][0]
                rules = own[name].restrictions or {}
                done[name] = formulas.compute(
                    formula,
                    values,
                    dtypes,
                    rules.get("result") or "string",
                    rules.get("decimals"),
                )

            for name in names:
                if name in compiled and name not in done:
                    work(name, frozenset())
            out.append({n: done[n] for n in names if n in done})
        return out

    def _name_files_from_relatives(
        self, records: list[RecordDTO], shapes: SchemaResolver
    ) -> list[RecordDTO]:
        """Name the files whose `filename_template` uses values from other
        records (a field of the record above, `{species.common}` through a
        reference, also from above). Batched like a table's derived columns: per
        schema, one lookup per level up and one for the references, however
        many records."""
        groups: dict[uuid.UUID, list[int]] = {}
        wanted: dict[uuid.UUID, list[str]] = {}
        for i, r in enumerate(records):
            shape = shapes(r.schema_id)
            if shape is None:
                continue
            if r.schema_id not in wanted:
                own = _own_names(shape)
                wanted[r.schema_id] = list(
                    dict.fromkeys(
                        col
                        for rf in shape.fields
                        if rf.field.dtype in ("file", "file_list")
                        for col in _outside_columns(
                            (rf.field.restrictions or {}).get("filename_template"),
                            own,
                        )
                    )
                )
            if wanted[r.schema_id] and any(
                r.data.get(rf.field.name)
                for rf in shape.fields
                if rf.field.dtype in ("file", "file_list")
            ):
                groups.setdefault(r.schema_id, []).append(i)
        if not groups:
            return records
        out = list(records)
        for schema_id, indexes in groups.items():
            shape = shapes(schema_id)
            assert shape is not None
            own = _own_names(shape)
            values = self._derived_values(
                shape.schema.name, [records[i] for i in indexes], wanted[schema_id]
            )
            for i, extra in zip(indexes, values):
                r = records[i]
                out[i] = dataclasses.replace(
                    r,
                    data=_apply_filename_templates(
                        r.data,
                        shape.fields,
                        _name_builtins(shape.schema.name, r.id),
                        own=own,
                        relatives=extra,
                    ),
                )
        return out

    def _attach_file_locations(
        self, records: list[RecordDTO], shapes: SchemaResolver | None = None
    ) -> list[RecordDTO]:
        """Stamp every file/file_list value with `location`: the volume it is
        stored on, that volume's state, whether it can be opened now, and when it
        can't, why (`reason`) and what to do about it (`fix`). One
        inventory lookup and one status check per volume for the whole batch,
        so a table of records with file columns doesn't fan out per file.
        Response-only: stripped again if a client echoes it back."""
        shapes = shapes or self._schema_svc.resolver()
        file_fields: list[list[str]] = []
        wanted: set[str] = set()
        for r in records:
            shape = shapes(r.schema_id)
            names = (
                [
                    rf.field.name
                    for rf in shape.fields
                    if rf.field.dtype in ("file", "file_list")
                ]
                if shape
                else []
            )
            file_fields.append(names)
            for name in names:
                wanted.update(
                    ref["sha256"]
                    for ref in _file_dicts(r.data.get(name))
                    if ref.get("sha256")
                )
        if not wanted:
            return records

        # Where each record's file is: the copy that record uses. Only a file
        # it doesn't point at yet (not on this computer when cited) is looked
        # up by its content.
        used = self._files.copies_used(r.id for r in records)
        unpointed = {
            ref["sha256"]
            for r, names in zip(records, file_fields)
            for name in names
            for ref in _file_dicts(r.data.get(name))
            if ref.get("sha256") and (r.id, ref["sha256"]) not in used
        }
        cited_by: dict[str, set[uuid.UUID]] = {}
        for r, names in zip(records, file_fields):
            for name in names:
                for ref in _file_dicts(r.data.get(name)):
                    if ref.get("sha256") in unpointed:
                        cited_by.setdefault(ref["sha256"], set()).add(r.id)
        location = self._locator(wanted, used, unpointed, cited_by)

        def decorate(record_id: uuid.UUID, value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    **value,
                    "location": location(record_id, value.get("sha256")),
                }
            if isinstance(value, list):
                return [decorate(record_id, item) for item in value]
            return value

        return [
            dataclasses.replace(
                r,
                data={
                    **r.data,
                    **{n: decorate(r.id, r.data.get(n)) for n in names if n in r.data},
                },
            )
            if names
            else r
            for r, names in zip(records, file_fields)
        ]

    def locate_pointed(
        self, pointed: dict[str, str | None]
    ) -> Callable[[str], dict[str, Any]]:
        """Where files are for an owner that isn't a live record (a release):
        `pointed` is each file's copy as that owner points at it (None: none
        yet). The same `location` a record's file value carries, worked out the
        same way (one status check per drive)."""
        nobody = uuid.UUID(int=0)
        used = {(nobody, sha): v for sha, v in pointed.items() if v}
        unpointed = {sha for sha, v in pointed.items() if not v}
        location = self._locator(set(pointed), used, unpointed)
        return lambda sha: location(nobody, sha)

    def _locator(
        self,
        wanted: set[str],
        used: dict[tuple[uuid.UUID, str], str],
        unpointed: set[str],
        cited_by: dict[str, set[uuid.UUID]] | None = None,
    ) -> Callable[[uuid.UUID, str | None], dict[str, Any]]:
        volume_of = self._files.locate_volumes(unpointed) if unpointed else {}
        following = self.files_from_server()
        # Records a device sent lately that cite a file not here: one lookup
        # for the batch, and only when there is such a file.
        arriving: set[tuple[uuid.UUID, str]] = set()
        if cited_by and not following:
            owners: dict[uuid.UUID, set[str]] = {}
            for sha, volume in volume_of.items():
                if volume is None:
                    for record_id in cited_by.get(sha, set()):
                        owners.setdefault(record_id, set()).add(sha)
            if owners:
                arriving = self.recently_received(owners)
        from_server = None in volume_of.values() and following
        unsent = self.not_on_server(wanted) if following else set()
        # Not here, and the server said it hasn't got it: nobody can fetch it,
        # so it is said as missing, with which computer added it. (Not asked
        # about yet: on the server, as usual, until the server is asked.)
        lost = (
            self.server_lacks(
                {sha for sha, v in volume_of.items() if v is None and sha in unsent}
            )
            if following
            else set()
        )
        why = self.why_not_here(sorted(lost)) if lost else {}
        status = {
            name: self._files.volume_status(name)
            for name in {v for v in volume_of.values() if v} | set(used.values())
        }

        def location(record_id: uuid.UUID, sha: str | None) -> dict[str, Any]:
            volume = used.get((record_id, sha or "")) or volume_of.get(sha or "")
            if volume is None and sha in lost:
                reason, fix = why.get(sha or "", not_on_server_yet(None))
                return {
                    "volume": None,
                    "state": "absent",
                    "available": False,
                    "reason": reason,
                    "fix": fix,
                    "sent": False,
                }
            if volume is None and from_server:
                # Another device added it: it is fetched when opened or
                # exported (and, unless this device keeps only what it opens,
                # in the background), so it is neither here nor lost.
                return {
                    "volume": None,
                    "state": "remote",
                    "available": None,
                    "reason": "Not downloaded to this computer yet.",
                    "fix": "Opening or exporting it downloads it from the server.",
                    "sent": sha not in unsent,
                }
            if volume is None and (record_id, sha or "") in arriving:
                return arriving_location()
            if volume is None:
                # Not on any volume we know of (yet): don't claim it is gone --
                # it may only be on a remote that hasn't been fetched.
                return {
                    "volume": None,
                    "state": "unknown",
                    "available": None,
                    "reason": "",
                    "fix": "",
                }
            st = status[volume]
            return {
                "volume": volume,
                "state": st.state,
                "available": st.reachable,
                # Why it can't be opened and what to do (blank when it can), so
                # a person is told which drive to plug in where the file is.
                "reason": st.reason,
                "fix": st.fix,
                # Whether the server holds it (False: other devices can't get
                # it yet). Only said while this project syncs.
                **({"sent": sha not in unsent} if following else {}),
            }

        return location

    def _label_references(
        self, records: list[RecordDTO], shapes: SchemaResolver | None = None
    ) -> list[RecordDTO]:
        """Batch-resolve reference/reference_list values to their target's
        natural_name, attached as RecordDTO.reference_labels -- one extra
        query for the whole batch instead of one per reference value, so a
        table of many records with reference columns doesn't fan out into
        per-row lookups. Call after _with_names (needs name-keyed data).

        Also stamps each record's collection name (`dataset_name`) and, for
        reference targets in a different collection, `reference_collections`
        -- the same batch, so showing where a record comes from costs no
        extra per-row lookups."""
        if not records:
            return records

        dataset_names: dict[uuid.UUID, str | None] = {}

        def dataset_name(dataset_id: uuid.UUID | None) -> str | None:
            if dataset_id is None:
                return None
            if dataset_id not in dataset_names:
                ds = self._datasets.get_by_id(
                    dataset_id,
                    include_deleted=True,
                    with_count=False,
                )
                dataset_names[dataset_id] = ds.name if ds else None
            return dataset_names[dataset_id]

        records = [
            dataclasses.replace(r, dataset_name=dataset_name(r.dataset_id))
            for r in records
        ]

        shapes = shapes or self._schema_svc.resolver()

        def fields_for(schema_id: uuid.UUID) -> list[ResolvedField]:
            shape = shapes(schema_id)
            return shape.fields if shape else []

        def reference_ids(
            data: dict[str, Any], fields: list[ResolvedField]
        ) -> set[uuid.UUID]:
            ids: set[uuid.UUID] = set()
            for rf in fields:
                if rf.field.dtype not in ("reference", "reference_list"):
                    continue
                value = data.get(rf.field.name)
                raw_values = (
                    value
                    if rf.field.dtype == "reference_list" and isinstance(value, list)
                    else [value]
                    if rf.field.dtype == "reference" and isinstance(value, str)
                    else []
                )
                for v in raw_values:
                    if isinstance(v, str):
                        try:
                            ids.add(uuid.UUID(v))
                        except ValueError:
                            pass
            return ids

        per_record_ids = [
            reference_ids(r.data, fields_for(r.schema_id)) for r in records
        ]
        all_ids: set[uuid.UUID] = set().union(*per_record_ids)
        if not all_ids:
            return records

        targets = self._records.list_by_ids(list(all_ids))
        target_dataset = {t.id: t.dataset_id for t in targets}
        label_by_id: dict[uuid.UUID, str | None] = {}
        target_data: dict[uuid.UUID, dict[str, Any]] = {}
        for t in targets:
            t_shape = shapes(t.schema_id)
            if t_shape is None:
                continue
            named_data = {t_shape.id_to_name.get(k, k): v for k, v in t.data.items()}
            target_data[t.id] = named_data
            label_by_id[t.id] = _natural_name(
                named_data,
                t_shape.fields,
                t_shape.schema.display_template,
                _name_builtins(t_shape.schema.name, t.id),
            )

        def foreign_collections(
            r: RecordDTO, ids: set[uuid.UUID]
        ) -> dict[str, str] | None:
            out = {
                str(i): name
                for i in ids
                if target_dataset.get(i) not in (None, r.dataset_id)
                and (name := dataset_name(target_dataset[i]))
            }
            return out or None

        reach_paths: dict[uuid.UUID, list[str]] = {}

        def reached_name(r: RecordDTO) -> str | None:
            """`r`'s name when its template uses `{ref.field}`: the one place
            another record's values are read. One hop only -- a target's own
            name, built above, leaves its references out."""
            shape = shapes(r.schema_id)
            template = shape.schema.display_template if shape else None
            if shape is None or not template:
                return r.natural_name
            if r.schema_id not in reach_paths:
                try:
                    names = templating.referenced_names(template)
                except ValidationError:
                    names = []
                reach_paths[r.schema_id] = [n for n in names if "." in n]
            paths = reach_paths[r.schema_id]
            if not paths:
                return r.natural_name
            values = dict(r.data)
            for path in paths:
                base, _, sub = path.partition(".")
                ref = r.data.get(base)
                try:
                    target_id = uuid.UUID(ref) if isinstance(ref, str) else None
                except ValueError:
                    target_id = None
                values[path] = (
                    target_data.get(target_id, {}).get(sub)
                    if target_id is not None
                    else None
                )
            return _natural_name(
                values,
                shape.fields,
                template,
                _name_builtins(shape.schema.name, r.id),
            )

        return [
            dataclasses.replace(
                r,
                reference_labels={str(i): label_by_id.get(i) for i in ids},
                reference_collections=foreign_collections(r, ids),
                natural_name=reached_name(r),
            )
            if ids
            else r
            for r, ids in zip(records, per_record_ids)
        ]

    def _fill_from_filenames(
        self,
        data: dict[str, Any],
        shape: ResolvedSchema | None,
        parent: RecordDTO | None,
        stored: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """`data` with each field that carries a `from_filename` rule read
        from the name of the file in the field the rule names
        (`domain/filename_extract`). The rule follows the file, not the
        field's emptiness, and this is the one place that decides:

        - A blank field with a file present is filled.
        - The source file changed in this save (on add, any file; on update,
          the incoming file's sha256 or name differs from the one in `stored`,
          the record's data as it was, by field name; for a `file_list`, the
          first file's): the value is read again and replaces what the field
          held, since the old value belonged to the old file.
        - The same file, and the field edited by hand or left as it was: what
          is there is kept. A hand edit is an override until the file changes,
          and a value given in the same save as the new file (on add, every
          value given) is such an edit, so a new file never discards it.
        - A name no pattern fits leaves the field as it is: a blank stays
          blank and a value stays, never blanked because the new file doesn't
          fit.

        An inherited file field's file is on the nearest record above
        (`parent`, then up); a child's save doesn't change it, so it counts as
        unchanged, and a child's field is filled only while blank. A parent's
        save never reaches into its children. A name a pattern fits but that
        doesn't read as the field's type is refused naming the field, as a
        typed value would be. Runs before defaults, validation and unique
        keys, so the derived value is held to all of them."""
        if shape is None:
            return data
        # Own fields only: a child record holds no values for inherited
        # fields (they live on the record above), so a rule on one is for
        # records of that schema.
        rules = [
            (rf.field, rule)
            for rf in shape.fields
            if rf.source_schema_name == shape.schema.name
            and (rule := filename_extract.rule_of(rf.field.restrictions))
        ]
        if not rules:
            return data
        inherited = {
            rf.field.name
            for rf in shape.fields
            if rf.source_schema_name != shape.schema.name
        }
        result = dict(data)
        for field, (source_name, patterns) in rules:
            source = shape.by_name.get(source_name)
            if source is None:
                continue
            incoming = result.get(source_name)
            filename = filename_extract.first_filename(incoming)
            if source_name in inherited:
                # An inherited file field's file is on a record above, which
                # this save doesn't change.
                changed = False
                if filename is None and parent is not None:
                    filename = self._filename_above(parent, str(source.id))
            elif stored is None:
                changed = filename is not None
            else:
                changed = filename_extract.first_file_key(
                    incoming
                ) != filename_extract.first_file_key(stored.get(source_name))
            current = result.get(field.name)
            blank = _is_blank_value(current)
            edited = not blank and (stored is None or current != stored.get(field.name))
            if filename is None or not (blank or (changed and not edited)):
                continue
            try:
                value = filename_extract.extract(filename, patterns, field.dtype)
            except ValueError as e:
                raise FieldValueError(
                    f"Field '{field.name}': could not be filled from '{filename}': {e}",
                    f"data.{field.id}",
                ) from None
            if value is not None:
                result[field.name] = value
        return result

    def _parent_if_needed(
        self, raw: RecordDTO, shape: ResolvedSchema | None, data: dict[str, Any]
    ) -> RecordDTO | None:
        """The record above `raw`, fetched only when a blank field's
        `from_filename` rule reads an inherited file field `data` has no file
        in: one query, and only for the records that need it."""
        if shape is None or raw.parent_record_id is None:
            return None
        own = {f.name for f in shape.schema.fields}
        for rf in shape.fields:
            rule = filename_extract.rule_of(rf.field.restrictions)
            if rule is None or not _is_blank_value(data.get(rf.field.name)):
                continue
            if rule[0] in own or filename_extract.first_filename(data.get(rule[0])):
                continue
            return self._records.get_by_id(raw.parent_record_id, include_deleted=True)
        return None

    def _filename_above(self, record: RecordDTO, field_id: str) -> str | None:
        """The name of the file in field `field_id` on `record` or the nearest
        record above it that has one (stored data is keyed by field id)."""
        current: RecordDTO | None = record
        while current is not None:
            filename = filename_extract.first_filename(current.data.get(field_id))
            if filename is not None:
                return filename
            if current.parent_record_id is None:
                return None
            current = self._records.get_by_id(
                current.parent_record_id, include_deleted=True
            )
        return None

    def _apply_defaults(
        self, data: dict[str, Any], shape: ResolvedSchema | None
    ) -> dict[str, Any]:
        """For any field with a default_value that is absent from data, insert the default."""
        if shape is None:
            return data
        result = dict(data)
        for rf in shape.fields:
            f = rf.field
            if f.default_value is not None and f.name not in result:
                result[f.name] = f.default_value
        return result

    def coerce_value(
        self,
        raw: str,
        dtype: str,
        field_name: str,
        restrictions: dict[str, Any] | None = None,
        timezone: str | None = None,
        collection_id: str | None = None,
    ) -> Any:
        """`collection_id` steers where a new file is stored (placement).
        `timezone` is the collection's zone, used to read an offset-less
        datetime; the field's own `timezone` restriction takes precedence."""
        if dtype in COMPUTED_DTYPES:
            raise ValidationError(
                f"Field '{field_name}' is a formula: it is worked out from the "
                "other fields, never set"
            )
        if dtype == "datetime":
            try:
                parsed = _parse_datetime(
                    raw, (restrictions or {}).get("timezone") or timezone
                )
            except ValueError:
                raise CoercionError(field_name, dtype, raw)
            _check_restrictions(parsed, dtype, restrictions or {}, field_name)
            return parsed
        if dtype == "geo":
            if isinstance(raw, dict):
                geometry = raw
            else:
                try:
                    geometry = geo_domain.parse_text(str(raw))
                except ValueError:
                    raise CoercionError(field_name, dtype, raw) from None
            _check_restrictions(geometry, dtype, restrictions or {}, field_name)
            return geometry
        field_unit = (restrictions or {}).get("unit")
        if dtype == "float" and isinstance(raw, str) and field_unit:
            # "1024 ft" is read in the field's unit; a bare number already is.
            try:
                number = units.to_field_unit(raw, field_unit)
            except ValueError:
                raise CoercionError(field_name, dtype, raw) from None
            except ValidationError as e:
                raise ValidationError(f"Field '{field_name}': {e}") from None
            _check_restrictions(number, dtype, restrictions or {}, field_name)
            return number
        if dtype == "file":
            path = Path(raw)
            if not path.exists():
                raise CoercionError(field_name, dtype, raw)
            file_ref = self._files.put_path(path, collection_id=collection_id)
            value = file_ref.to_dict()
            _check_restrictions(value, dtype, restrictions or {}, field_name)
            return value

        if dtype == "file_list":
            path = Path(raw)
            if not path.exists():
                raise CoercionError(field_name, dtype, raw)
            file_ref = self._files.put_path(path, collection_id=collection_id)
            file_list_value = [file_ref.to_dict()]
            _check_restrictions(file_list_value, dtype, restrictions or {}, field_name)
            return file_list_value

        if dtype == "reference":
            record = self._records.get_by_prefix(raw)
            if not record:
                raise CoercionError(field_name, dtype, raw, extra="record not found")
            target_schema = (restrictions or {}).get("schema")
            if target_schema and record.schema_name != target_schema:
                raise CoercionError(
                    field_name,
                    dtype,
                    raw,
                    extra=f"record has schema '{record.schema_name}', expected '{target_schema}'",
                )
            return str(record.id)

        if dtype == "reference_list":
            if isinstance(raw, str):
                items: list[Any] = [x.strip() for x in raw.split(",") if x.strip()]
            else:
                items = list(raw)
            target_schema = (restrictions or {}).get("schema")
            result = []
            for item in items:
                record = self._records.get_by_prefix(str(item))
                if not record:
                    raise CoercionError(
                        field_name, dtype, str(item), extra="record not found"
                    )
                if target_schema and record.schema_name != target_schema:
                    raise CoercionError(
                        field_name,
                        dtype,
                        str(item),
                        extra=f"record has schema '{record.schema_name}', expected '{target_schema}'",
                    )
                result.append(str(record.id))
            return result

        coerce = _COERCE.get(dtype)
        if coerce is None:
            raise CoercionError(field_name, dtype, raw)
        try:
            value = coerce(raw)
        except (ValueError, TypeError):
            raise CoercionError(field_name, dtype, raw)
        _check_restrictions(value, dtype, restrictions or {}, field_name)
        return value

    def _normalise_datetimes(
        self,
        data: dict[str, Any],
        shape: ResolvedSchema | None,
        dataset_timezone: str | None,
        unchanged: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store every datetime value as a UTC ISO string.

        Offset-less values are read in the field's `timezone` restriction,
        else the collection's zone, else as UTC. `unchanged` (the record's
        current values) lets an update skip fields the caller merely echoed
        back: the UI re-sends the whole record on every edit, and a legacy
        offset-less value must not be re-read in a zone set after it was
        stored -- that would silently shift it.
        """
        if shape is None:
            return data
        out = dict(data)
        for name, value in data.items():
            field = shape.by_name.get(name)
            if field is None or field.dtype != "datetime":
                continue
            if not isinstance(value, str) or (
                unchanged is not None and unchanged.get(name) == value
            ):
                continue
            tz = field.restrictions.get("timezone") or dataset_timezone
            try:
                out[name] = _parse_datetime(value, tz)
            except ValueError:
                raise ValidationError(
                    f"Field '{name}': '{value}' is not a valid datetime "
                    "(use e.g. 2024-03-01T15:30 or 2024-03-01T15:30:00-06:00)"
                ) from None
        return out

    def _check_unique(
        self,
        shape: ResolvedSchema | None,
        dataset_id: uuid.UUID,
        parent_record_id: uuid.UUID | None,
        id_data: dict[str, Any],
        exclude_id: uuid.UUID | None = None,
        unchanged: dict[str, Any] | None = None,
        cache: IncomingCache | None = None,
    ) -> None:
        """Refuse a record that would share a uniqueness key's values with
        another live record of its schema in the same place (under the same
        parent, or in the same collection at the top level). Keys with a blank
        value are not checked, and, on update, neither is a key whose values
        are the stored ones: saving an unrelated field mustn't be blocked by an
        old duplicate. `id_data` is keyed by field id, as stored."""
        if shape is None or not shape.schema.unique_keys:
            return
        for key in shape.schema.unique_keys:
            values = key_values(id_data, key)
            if values is None:
                continue
            if unchanged is not None and key_values(unchanged, key) == values:
                continue
            if cache is not None and cache.free:
                mark = _key_mark(
                    dataset_id, shape.schema.id, parent_record_id, key, values
                )
                if mark in cache.free and mark not in cache.made:
                    continue  # read already: nothing held has these values
            other = self._records.find_key_match(
                dataset_id,
                shape.schema.id,
                parent_record_id,
                dict(zip(key, values)),
                exclude_id=exclude_id,
            )
            if other is None:
                continue
            names = [shape.id_to_name.get(i, i) for i in key]
            raise DuplicateRecordError(
                f"A {shape.schema.display_name} with the same "
                f"{_join_names(names)} already exists: {self._deleted_name(other)}"
                f" ({str(other.id)[:8]}). {_join_names(names, cap=True)} must be "
                "unique"
                + (
                    " within its parent."
                    if parent_record_id
                    else " within the collection."
                ),
                existing_id=str(other.id),
                fields=names,
                existing_name=self._deleted_name(other),
            )

    def _check_references(
        self,
        data: dict[str, Any],
        shape: ResolvedSchema | None,
        dataset: DatasetDTO,
        unchanged: dict[str, Any] | None = None,
        cache: IncomingCache | None = None,
    ) -> None:
        """Every reference/reference_list value must point at a live record in
        this collection or in a global one (see civex.domain.scopes). Values
        equal to the record's stored ones (`unchanged`) are not re-checked, so
        editing a record never fails over a reference it already held."""
        if shape is None:
            return
        changed = _changed_values(data, unchanged)
        wanted: list[tuple[str, Any]] = []
        for rf in shape.fields:
            field = rf.field
            if field.dtype not in ("reference", "reference_list"):
                continue
            value = changed.get(field.name)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                wanted.append((field.name, item))
        self._check_reference_targets(wanted, dataset, cache)

    def _check_reference_targets(
        self,
        wanted: list[tuple[str, Any]],
        dataset: DatasetDTO,
        cache: IncomingCache | None = None,
    ) -> None:
        """Check every (field name, record id) in `wanted` against `dataset`:
        the target must be a live record here or in a global collection. All
        the targets are fetched together, and each collection looked up once,
        however many references a record holds."""
        owners = cache.datasets if cache is not None else None
        for problem in self.reference_problems(wanted, dataset.id, owners, cache):
            if problem:
                raise ValidationError(problem)

    def reference_problems(
        self,
        wanted: list[tuple[str, Any]],
        dataset_id: uuid.UUID,
        owners: dict[uuid.UUID, DatasetDTO | None] | None = None,
        cache: IncomingCache | None = None,
    ) -> list[str | None]:
        """For each (field name, record id) in `wanted`, why a record in
        collection `dataset_id` can't hold that reference, or None: the target
        must be a live record there or in a global collection. The one rule
        behind a save and the data check. All the targets are fetched
        together, and each collection looked up once (`owners` carries the
        lookups across calls), however many references there are."""
        if not wanted:
            return []
        ids: list[uuid.UUID | None] = []
        for _, raw in wanted:
            try:
                ids.append(uuid.UUID(str(raw)))
            except ValueError:
                ids.append(None)
        found = [i for i in ids if i is not None]
        targets: dict[uuid.UUID, Any] = {}
        if found:
            # (what a run has read already is not asked for again)
            held = cache.places if cache is not None else {}
            targets = {i: held[i] for i in found if held.get(i) is not None}
            asked = [i for i in found if i not in held]
            targets.update({t.id: t for t in self._records.list_by_ids(asked)})
        owners = {} if owners is None else owners
        problems: list[str | None] = []
        for (field_name, raw), target_id in zip(wanted, ids):
            if target_id is None:
                problems.append(f"Field '{field_name}': '{raw}' is not a record id")
                continue
            target = targets.get(target_id)
            if target is None or target.deleted_at is not None:
                problems.append(f"Field '{field_name}': record {raw} not found")
                continue
            if target.dataset_id == dataset_id:
                problems.append(None)
                continue
            if target.dataset_id not in owners:
                owners[target.dataset_id] = self._datasets.get_by_id(
                    target.dataset_id,
                    include_deleted=True,
                    with_count=False,
                )
            owner = owners[target.dataset_id]
            if owner is None or not can_reference(dataset_id, owner.id, owner.scope):
                where = f"collection '{owner.name}'" if owner else "another collection"
                problems.append(
                    f"Field '{field_name}': record {str(target_id)[:8]} is in "
                    f"{where}, which is local. A record can only reference "
                    f"records in its own collection or in a global collection."
                )
                continue
            problems.append(None)
        return problems

    def referrer_counts(self, record_id: str) -> list[ReferrerGroupDTO]:
        """What points at this record: live records holding a reference to it,
        grouped by (collection, schema, field) with a record count. A record
        stores only its own schema's fields, so the referrer's schema is the
        one that owns the field. Sorted by collection, schema, field."""
        target = self.get(record_id)
        field_map = self._reference_field_map(target.schema_name)
        datasets: dict[uuid.UUID, Any] = {}
        result = []
        for dataset_id, schema_name, field_id, count in self._records.referrer_groups(
            target.id, [uuid.UUID(f) for f in field_map]
        ):
            if dataset_id not in datasets:
                datasets[dataset_id] = self._datasets.get_by_id(
                    dataset_id,
                    include_deleted=True,
                    with_count=False,
                )
            ds = datasets[dataset_id]
            field_name, dtype = field_map[str(field_id)]
            result.append(
                ReferrerGroupDTO(
                    dataset_id=dataset_id,
                    dataset_name=ds.name if ds else "",
                    schema_name=schema_name,
                    field_name=field_name,
                    dtype=dtype,
                    count=count,
                )
            )
        result.sort(key=lambda g: (g.dataset_name, g.schema_name, g.field_name))
        return result

    def collection_referrers(
        self, dataset_id: uuid.UUID, limit: int = 5
    ) -> tuple[int, list[tuple[RecordDTO, dict[str, str]]]]:
        """Records in *other* collections that reference a record in this one --
        how many there are, and the first `limit` with their referencing
        fields. What stops a global collection from being made local or
        deleted."""
        field_map = self._reference_field_map()
        total, pairs = self._records.referrers_into_dataset(
            dataset_id, [uuid.UUID(f) for f in field_map], limit
        )
        fields: dict[uuid.UUID, dict[str, str]] = {}
        for record_id, field_id in pairs:
            fields.setdefault(record_id, {})[str(field_id)] = field_map[str(field_id)][
                0
            ]
        records = {r.id: r for r in self._records.list_by_ids(list(fields))}
        return total, [(records[rid], f) for rid, f in fields.items() if rid in records]

    def collection_referrer_block(
        self, dataset_id: uuid.UUID, sees: Callable[[Any], bool]
    ) -> str | None:
        """The one rule for deleting a global collection or making it local:
        "hidden" when a record the caller cannot see (`sees` says which
        collections they can) in another collection points into it, "visible"
        when only records they can see do, else None. The service and the sync
        authority both ask it."""
        field_map = self._reference_field_map()
        where = self._records.referrer_collections_into_dataset(
            dataset_id, [uuid.UUID(f) for f in field_map]
        )
        if any(not sees(w) for w in where):
            return "hidden"
        return "visible" if where else None

    def hidden_referrers_of_records(
        self,
        target_ids: set[uuid.UUID],
        sees: Callable[[Any], bool],
        exclude: set[uuid.UUID],
    ) -> bool:
        """Whether a record the caller cannot see, and that is not in
        `exclude` (what is deleted with them), points at any of these."""
        field_map = self._reference_field_map()
        if not field_map or not target_ids:
            return False
        holders = self._records.referrer_places_of(
            list(target_ids), [uuid.UUID(f) for f in field_map]
        )
        return any(
            not sees(where) for rid, where in holders.items() if rid not in exclude
        )

    def patched_data(
        self, record_id: str, fields: dict[str, Any]
    ) -> tuple[RecordDTO, dict[str, Any] | None]:
        """The record as it is *now*, and the whole data it would hold with only
        `fields` changed (None when they already hold those values, so there is
        nothing to write). `update` replaces a record's whole data, so a caller
        that knows only some fields must start from the current ones: this is
        the one place that does, for `patch` and for a plugin's `patch_record`."""
        current = self.get(record_id)
        return current, _patched(without_file_locations(current.data), fields)

    def patch(
        self,
        record_id: str,
        fields: dict[str, Any],
        _job_depth: int = 0,
        _cause: dict[str, Any] | None = None,
    ) -> RecordDTO:
        """Change only `fields`; every other field stays as it is now. Writes
        nothing (no history, no triggers) when they already hold these values."""
        current, data = self.patched_data(record_id, fields)
        if data is None:
            return current
        return self.update(record_id, data, _job_depth=_job_depth, _cause=_cause)

    def field_values(
        self, pairs: list[tuple[str, str]]
    ) -> dict[tuple[str, str], FieldValueDTO]:
        """Describe (record id, field id) pairs for a person: see `FieldValueDTO`.
        A fixed number of queries however many pairs. A pair whose record is gone
        is left out."""
        shapes = self._schema_svc.resolver()
        records = {str(r.id): r for r in self.labels([rid for rid, _ in pairs])}
        out: dict[tuple[str, str], FieldValueDTO] = {}
        for rid, fid in dict.fromkeys(pairs):
            record = records.get(rid)
            if record is None:
                continue
            shape = shapes(record.schema_id)
            name = shape.id_to_name.get(fid) if shape else None
            field = shape.by_name.get(name) if shape and name else None
            out[(rid, fid)] = FieldValueDTO(
                record_id=rid,
                record_name=record.natural_name,
                dataset_name=record.dataset_name,
                schema_name=record.schema_name,
                field_name=name if field else None,
                field_label=field.display_name if field else None,
                dtype=field.dtype if field else None,
                value=record.data.get(name) if name else None,
                record_deleted=record.deleted_at is not None,
                field_deleted=bool(shape and fid in shape.deleted_by_id),
            )
        return out

    def _check_parent(
        self, parent: RecordDTO, dataset: DatasetDTO, schema: SchemaDTO
    ) -> None:
        """A child record's parent is in the same collection and of the schema
        this one inherits from."""
        if parent.dataset_id != dataset.id:
            raise ValidationError(
                f"Parent record must belong to dataset '{dataset.name}'"
            )
        if parent.schema_id != schema.parent_id:
            expected = (
                self._schema_svc._repo.get_by_id(schema.parent_id, include_deleted=True)
                if schema.parent_id
                else None
            )
            raise ValidationError(
                f"Parent record uses schema '{parent.schema_name}', "
                f"expected '{expected.name if expected else schema.parent_id}'"
            )

    def _record_at(
        self,
        record_id: uuid.UUID,
        cache: IncomingCache | None,
        include_deleted: bool = False,
    ) -> Any:
        """A record by id, from what a run has read when it has (the record is
        then as `get_by_id` finds it, for what is asked of it here)."""
        if cache is not None and record_id in cache.places:
            found = cache.places[record_id]
            if found is not None and not include_deleted and found.deleted_at:
                return None
            return found
        return self._records.get_by_id(record_id, include_deleted=include_deleted)

    def shape_of(self, state: dict[str, Any], cache: IncomingCache) -> Any:
        """The resolved schema a record state names (None when there is none),
        as `check_incoming` finds it."""
        return cache.shapes(uuid.UUID(str(state["schema_id"])))

    @staticmethod
    def cites_records(state: dict[str, Any], shape: Any) -> bool:
        """Whether a record state holds a value that refers to another record."""
        data = state.get("data") or {}
        return isinstance(data, dict) and any(
            rf.field.dtype in ("reference", "reference_list")
            and data.get(str(rf.field.id)) is not None
            for rf in shape.fields
        )

    def incoming_cache(self) -> IncomingCache:
        """For a run of `check_incoming` calls that change neither schemas nor
        collections: each schema and collection is read once for the run."""
        return IncomingCache(self._schema_svc.resolver)

    def unique_marks(
        self,
        state: dict[str, Any],
        shape: Any,
    ) -> list[tuple[Any, ...]]:
        """What each uniqueness key of the schema is for this record state (a
        key with a blank value is not one): the same two records have the same
        marks."""
        if not shape.schema.unique_keys:
            return []
        try:
            where = uuid.UUID(str(state["dataset_id"]))
            parent = (
                uuid.UUID(str(state["parent_record_id"]))
                if state.get("parent_record_id")
                else None
            )
        except (KeyError, ValueError):
            return []
        data = state.get("data") or {}
        marks = []
        for key in shape.schema.unique_keys:
            values = key_values(data, key) if isinstance(data, dict) else None
            if values is not None:
                marks.append(_key_mark(where, shape.schema.id, parent, key, values))
        return marks

    def prefetch_incoming(
        self, cache: IncomingCache, states: list[dict[str, Any]]
    ) -> None:
        """Read, for record states about to be made, what `check_incoming` will
        ask of the records: where each record they sit under or point at is
        (one query for all), and which of their uniqueness keys nothing stored
        holds (one per collection and schema). Records the run writes are
        added with `note_made`; a write by anything else is `clear_records`."""
        cache.stale = False
        if not cache.use_records:
            return
        want: set[uuid.UUID] = set()
        keys: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[Any, ...]]] = {}
        places: dict[tuple[Any, ...], tuple[uuid.UUID | None, dict[str, Any]]] = {}
        for state in states:
            try:
                schema_id = uuid.UUID(str(state["schema_id"]))
                where = uuid.UUID(str(state["dataset_id"]))
            except (KeyError, ValueError):
                continue
            shape = cache.shapes(schema_id)
            data = state.get("data")
            if shape is None or not isinstance(data, dict):
                continue
            for raw in [state.get("parent_record_id")] + [
                item
                for rf in shape.fields
                if rf.field.dtype in ("reference", "reference_list")
                for item in _as_list(data.get(str(rf.field.id)))
            ]:
                try:
                    if raw:
                        want.add(uuid.UUID(str(raw)))
                except ValueError:
                    pass
            for mark in self.unique_marks(state, shape):
                if mark in cache.free or mark in places:
                    continue
                key = dict(zip(mark[3], key_values(data, list(mark[3])) or []))
                places[mark] = (mark[2], key)
                keys.setdefault((where, schema_id), []).append(mark)
        want -= cache.places.keys()
        if want:
            found = self._records.placement_of(list(want))
            for rid in want:
                cache.places[rid] = found.get(rid)
        for (where, schema_id), marks in keys.items():
            for at in range(0, len(marks), 100):
                chunk = marks[at : at + 100]
                if not self._records.any_key_match(
                    where, schema_id, [places[m] for m in chunk]
                ):
                    cache.free.update(chunk)
                    continue
                for mark in chunk:  # one holds: which, is asked of each
                    if not self._records.any_key_match(
                        where, schema_id, [places[mark]]
                    ):
                        cache.free.add(mark)

    def note_made(
        self,
        cache: IncomingCache,
        state: dict[str, Any],
        shape: Any,
    ) -> None:
        """A record state the run is about to write: it is there for what comes
        after it (a record under it, one pointing at it, one sharing its key)."""
        if not cache.use_records:
            return
        record_id = uuid.UUID(str(state["id"]))
        gone = state.get("deleted_at")
        cache.places[record_id] = RecordPlace(
            record_id,
            uuid.UUID(str(state["dataset_id"])),
            shape.schema.id,
            shape.schema.name,
            _stamp_of(gone) if gone else None,
        )
        if not gone:  # a deleted record holds no unique key
            cache.made.update(self.unique_marks(state, shape))

    def check_incoming(
        self,
        state: dict[str, Any],
        head: dict[str, Any] | None,
        cache: IncomingCache | None = None,
    ) -> None:
        """Refuse a record state sent by another device that a person's own write
        would have refused: values outside their field's restrictions,
        references to records that aren't there or can't be referenced, a
        uniqueness key already taken, a collection that doesn't hold its schema,
        a parent that isn't right. The same checks as `add`/`update`, so sync
        can't bring in what an edit here couldn't.

        `state` is the record as it would become (values keyed by field id, as
        stored) and `head` what is held now, or None for a record not held. What
        `head` already holds is not checked again, so an unrelated edit is never
        refused over an old problem. Required fields are not checked: they were
        when the change was made, and the schema may have moved on since.
        Writing is not done here (that is `SyncRepository.apply_snapshot`), and
        neither are history or triggers: the change is already in the feed."""
        if state.get("deleted_at"):
            return  # a record going away has nothing to satisfy
        try:
            record_id = uuid.UUID(str(state["id"]))
            dataset_id = uuid.UUID(str(state["dataset_id"]))
            schema_id = uuid.UUID(str(state["schema_id"]))
            parent_id = (
                uuid.UUID(str(state["parent_record_id"]))
                if state.get("parent_record_id")
                else None
            )
        except (KeyError, ValueError):
            raise ValidationError("The record's ids are not valid") from None
        data = state.get("data") or {}
        if not isinstance(data, dict):
            raise ValidationError("The record's values are not an object")
        shape = (cache.shapes if cache else self._schema_svc.resolver())(schema_id)
        if shape is None:
            raise ValidationError("The record's schema does not exist here")
        if cache is not None and dataset_id in cache.datasets:
            dataset = cache.datasets[dataset_id]
        else:
            dataset = self._datasets.get_by_id(
                dataset_id, include_deleted=True, with_count=False
            )
            if cache is not None:
                cache.datasets[dataset_id] = dataset
        if dataset is None or dataset.deleted_at is not None:
            raise ValidationError("The record's collection does not exist here")
        # A record can't be live inside something deleted: an edit that meets
        # a delete keeps the record itself, never brings it back into a
        # deleted schema or under a deleted parent (restore says the same:
        # `restore_plan` is blocked by them).
        if shape.schema.deleted_at is not None:
            raise ValidationError(
                f"Its schema '{shape.schema.name}' was deleted on the server"
            )
        coming_back = head is None or bool(head.get("deleted_at"))
        if parent_id is not None and coming_back:
            # Made, or brought back, under a record that is deleted: what a
            # person's add or restore here would be refused. (A record already
            # live under one, left by deleting a parent schema, can still be
            # edited, as it can here.)
            above = self._record_at(parent_id, cache, include_deleted=True)
            if above is not None and above.deleted_at is not None:
                raise ValidationError(
                    "The record it sits under was deleted on the server"
                )

        moved = head is not None and (
            str(head.get("parent_record_id") or "") != str(parent_id or "")
            or str(head.get("dataset_id")) != str(dataset_id)
        )
        if head is None or head.get("deleted_at") or moved:
            # Made, brought back, or moved: only where it could be added.
            if shape.schema.parent_id:
                parent = self._record_at(parent_id, cache) if parent_id else None
                if parent is None:
                    raise ValidationError(
                        f"Schema '{shape.schema.name}' inherits from another "
                        "schema: its parent record does not exist here"
                    )
                self._check_parent(parent, dataset, shape.schema)
            elif moved and parent_id is not None:
                raise ValidationError(
                    f"A '{shape.schema.name}' sits at the top of a collection, "
                    "not inside another record"
                )
        # A record that is deleted here and comes back is checked in full: its
        # stored values say nothing about whether they still fit.
        before = head.get("data") or {} if head and not head.get("deleted_at") else None
        named = self._ids_to_names(data, shape)
        before_named = self._ids_to_names(before, shape) if before is not None else None
        self._validate_data(_changed_values(named, before_named), shape)
        with self.as_caller():
            self._check_references(
                named, shape, dataset, unchanged=before_named, cache=cache
            )
        self._check_unique(
            shape,
            dataset.id,
            parent_id,
            data,
            exclude_id=record_id,
            unchanged=before,
            cache=cache,
        )

    def _validate_data(
        self, data: dict[str, Any], shape: ResolvedSchema | None
    ) -> None:
        """Validate all field values in data against their restrictions."""
        if shape is None:
            return
        for name, value in data.items():
            field = shape.by_name.get(name)
            if field is None or value is None:
                continue
            try:
                _check_restrictions(value, field.dtype, field.restrictions, name)
            except FieldValueError:
                raise
            except ValidationError as e:
                raise FieldValueError(str(e), f"data.{field.id}") from e

    def validate(self, data: dict[str, Any], fields: list[ResolvedField]) -> None:
        missing = [
            rf.field.name
            for rf in fields
            if rf.field.required and rf.field.name not in data
        ]
        if missing:
            raise ValidationError(f"Missing required fields: {', '.join(missing)}")

    def get_resolved_fields(self, schema_name: str) -> list[ResolvedField]:
        """
        Fields to prompt for when adding/updating a record of this schema.
        For child schemas, only own fields are returned — inherited fields
        live on the parent record.
        """
        schema = self._schema_svc.get(schema_name)
        if schema.parent_id:
            return [
                ResolvedField(field=f, source_schema_name=schema.name)
                for f in schema.fields
            ]
        return self._schema_svc.collect_fields(schema)

    def add(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        parent_record_id: str | None = None,
        _job_depth: int = 0,
        _cause: dict[str, Any] | None = None,
        with_labels: bool = True,
        record_id: uuid.UUID | None = None,
        created_at: _dt | None = None,
        updated_at: _dt | None = None,
    ) -> RecordDTO:
        """Create a record. `with_labels=False` skips resolving its reference
        values' display names and collection for the returned DTO (a few
        queries) -- for loops, like an import, that discard the result.
        `record_id` and the dates are for a record brought in from another
        project (a bundle): it keeps its identity, so what sits inside it and
        what references it still mean the same; the caller has checked the id
        is free."""
        dataset = self._datasets.get_by_name(dataset_name, with_count=False)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")
        self._permissions.require(permissions.WRITE_RECORDS, dataset.id)

        schema = self._schema_svc.get(schema_name)
        shape = self._schema_svc.resolve(schema)
        parent_record = (
            self._records.get_by_prefix(parent_record_id)
            if schema.parent_id and parent_record_id
            else None
        )
        # Fields read from a file's name first, then defaults, then validation.
        data = self._fill_from_filenames(data, shape, parent_record)
        data = self._apply_defaults(data, shape)
        if shape is not None:
            data = _strip_derived_file_keys(data, shape.fields)
        data = self._normalise_datetimes(data, shape, dataset.timezone)

        resolved_parent_id = None
        if schema.parent_id:
            if not parent_record_id:
                raise ValidationError(
                    f"Schema '{schema.name}' inherits from another schema — a parent record ID is required"
                )
            if not parent_record:
                raise NotFoundError(f"Parent record '{parent_record_id}' not found")
            self._check_parent(parent_record, dataset, schema)
            resolved_parent_id = parent_record.id
            own_fields = [
                ResolvedField(field=f, source_schema_name=schema.name)
                for f in schema.fields
            ]
            self.validate(data, own_fields)
        else:
            self.validate(data, shape.fields)

        self._validate_data(data, shape)
        self._check_file_rights(dataset.id, {}, data)
        self._check_references(data, shape, dataset)
        id_data = self._names_to_ids(data, shape)
        self._check_unique(shape, dataset.id, resolved_parent_id, id_data)
        dto = self._records.create(
            dataset_id=dataset.id,
            schema_id=schema.id,
            data=id_data,
            parent_record_id=resolved_parent_id,
            id=record_id,
            created_at=created_at,
            updated_at=updated_at,
        )
        shapes = self._schema_svc.resolver()
        shapes.prime(shape)
        named = self._with_names(dto, shapes)
        if self._audit:
            self._audit.log_change(
                "create", "record", dto.id, None, self._snapshot(dto)
            )
        if self._job_svc:
            self._job_svc.trigger_for_record(
                named, "record_created", depth=_job_depth, cause=_cause
            )
            if named.data:
                # Also fire record_updated so field-specific triggers (e.g. triggered on
                # a particular field being set) fire even when the record is first created.
                set_fields = {k for k, v in named.data.items() if v is not None}
                if set_fields:
                    self._job_svc.trigger_for_record(
                        named,
                        "record_updated",
                        changed_fields=set_fields,
                        depth=_job_depth,
                        changes={k: (None, named.data[k]) for k in set_fields},
                        cause=_cause,
                    )
        return (
            self._attach_reference_labels([named], shapes)[0] if with_labels else named
        )

    def exists(self, record_id: str) -> bool:
        """Whether a record with this id is here, live or deleted."""
        try:
            rid = uuid.UUID(record_id)
        except ValueError:
            return False
        return self._records.get_by_id(rid, include_deleted=True) is not None

    def get(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id)
        if not record:
            raise NotFoundError(f"Record '{record_id}' not found")
        return self._attach_open_notes(
            self._attach_reference_labels([self._with_names(record)])
        )[0]

    def files_for_zip(
        self,
        record_id: str,
        field_name: str | None = None,
        field_names: list[str] | None = None,
    ) -> list[tuple[str, FileRef]]:
        """(zip_entry_name, FileRef) pairs for every file/file_list value on
        this record, or restricted to specific field(s): `field_name` for a
        single field (404s if it doesn't resolve to a file/file_list field),
        or `field_names` for a set (silently ignoring any that don't --
        for callers like view export where the column list was validated
        once at save time and may have drifted since). `zip_entry_name` is
        each file's resolved filename (see `resolve_filename`),
        collision-suffixed against every other entry so two files never
        overwrite each other."""
        record = self.get(record_id)
        schema = self._schema_svc._repo.get_by_id(
            record.schema_id, include_deleted=True
        )
        if schema is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        fields = self._schema_svc.collect_fields(schema)
        file_fields = [
            rf.field for rf in fields if rf.field.dtype in ("file", "file_list")
        ]

        if field_names is not None:
            wanted = set(field_names)
            file_fields = [f for f in file_fields if f.name in wanted]
        elif field_name is not None:
            target = next(
                (rf.field for rf in fields if rf.field.name == field_name), None
            )
            if target is None:
                raise NotFoundError(
                    f"Field '{field_name}' not found on schema '{schema.name}'"
                )
            if target.dtype not in ("file", "file_list"):
                raise ValidationError(
                    f"Field '{field_name}' is type '{target.dtype}', not file/file_list"
                )
            file_fields = [target]

        refs: list[dict[str, Any]] = []
        for f in file_fields:
            value = record.data.get(f.name)
            if isinstance(value, dict):
                refs.append(value)
            elif isinstance(value, list):
                refs.extend(v for v in value if isinstance(v, dict))

        if len(refs) > MAX_ZIP_FILE_COUNT:
            raise ValidationError(
                f"Record has {len(refs)} files, exceeding the zip export limit "
                f"of {MAX_ZIP_FILE_COUNT}"
            )
        total_size = sum(int(r.get("size", 0)) for r in refs)
        if total_size > MAX_ZIP_TOTAL_SIZE:
            raise ValidationError(
                f"Total file size ({total_size} bytes) exceeds the zip export "
                f"limit of {MAX_ZIP_TOTAL_SIZE} bytes"
            )

        used_names: set[str] = set()
        entries: list[tuple[str, FileRef]] = []
        for ref_dict in refs:
            name = ref_dict.get("resolved_filename") or ref_dict["filename"]
            # resolved_filename is already sanitised by resolve_filename(); the raw
            # `filename` fallback (an unsanitised, user-supplied upload name) is not
            # -- clean it here so a "/" or ".." in it can't escape the zip entry.
            name = _UNSAFE_FILENAME_CHARS_RE.sub("_", name).strip() or "file"
            entries.append(
                (_unique_zip_name(name, used_names), FileRef.from_dict(ref_dict))
            )
        return entries

    def update(
        self,
        record_id: str,
        data: dict[str, Any],
        _job_depth: int = 0,
        _cause: dict[str, Any] | None = None,
    ) -> RecordDTO:
        raw = self._records.get_by_prefix(record_id)
        if not raw:
            raise NotFoundError(f"Record '{record_id}' not found")
        self._permissions.require(permissions.WRITE_RECORDS, raw.dataset_id)
        shapes = self._schema_svc.resolver()
        dataset = (
            self._datasets.get_by_id(
                raw.dataset_id,
                include_deleted=True,
                with_count=False,
            )
            if raw.dataset_id
            else None
        )
        named, _ = self._write_update(
            raw, data, shapes, dataset, _job_depth=_job_depth, _cause=_cause
        )
        return self._attach_reference_labels([named], shapes)[0]

    def _checked_update(
        self,
        raw: RecordDTO,
        data: dict[str, Any],
        shape: ResolvedSchema | None,
        dataset: DatasetDTO | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """What `raw` would store if saved with `data` (its whole data, by
        field name), checked as every save is: values read from file names,
        defaults, datetimes normalised, restrictions, references and unique
        keys. The record's data as it was (by name) and the data to store (by
        field id); raises `ValidationError` and writes nothing. The one set of
        checks behind `update` and a bulk edit's plan."""
        old_data = self._ids_to_names(raw.data, shape)
        # Fields read from a file's name first, then defaults, then validation.
        # The stored data says whether the file changed; the parent is only
        # looked up when a rule reads an inherited file field the record
        # itself doesn't carry.
        data = self._fill_from_filenames(
            data,
            shape,
            self._parent_if_needed(raw, shape, data),
            stored=old_data,
        )
        data = self._apply_defaults(data, shape)
        if shape is not None:
            data = _strip_derived_file_keys(data, shape.fields)
        data = self._normalise_datetimes(
            data,
            shape,
            dataset.timezone if dataset else None,
            unchanged=old_data,
        )
        # Only what this save changes is checked (`_changed_values`): a value
        # the record already holds may break a rule tightened since, and must
        # not stop an edit to another field (the data check finds it).
        self._validate_data(_changed_values(data, old_data), shape)
        self._check_file_rights(raw.dataset_id, old_data, data)
        if dataset:
            self._check_references(data, shape, dataset, unchanged=old_data)
        id_data = self._names_to_ids(data, shape)
        if shape is not None and shape.deleted_by_id:
            # Saving replaces the record's data. Values held for deleted fields
            # aren't part of what the caller sent, and must survive it, or
            # restoring the field would bring back an empty one.
            kept = {k: v for k, v in raw.data.items() if k in shape.deleted_by_id}
            id_data = {**kept, **id_data}
        if dataset:
            self._check_unique(
                shape,
                dataset.id,
                raw.parent_record_id,
                id_data,
                exclude_id=raw.id,
                unchanged=raw.data,
            )
        return old_data, id_data

    def _write_update(
        self,
        raw: RecordDTO,
        data: dict[str, Any],
        shapes: SchemaResolver,
        dataset: DatasetDTO | None,
        _job_depth: int = 0,
        _cause: dict[str, Any] | None = None,
    ) -> tuple[RecordDTO, int]:
        """Save `raw` with `data` (checked first, `_checked_update`), log it and
        fire its triggers: the record as saved, by name and without reference
        labels, and how many workflow runs were queued. Permission is the
        caller's to ask."""
        shape = shapes(raw.schema_id)
        old_data, id_data = self._checked_update(raw, data, shape, dataset)
        dto = self._records.update(id=raw.id, data=id_data)
        named = self._with_names(dto, shapes)
        # What was stored, by field name, with nothing the server adds on a read
        # (`resolved_filename`): what "before" is, so it is what "after" must be,
        # or every file field would look edited on every save.
        new_data = self._ids_to_names(dto.data, shape)
        if self._audit:
            self._audit.log_change(
                "update", "record", raw.id, self._snapshot(raw), self._snapshot(dto)
            )
        if self._job_svc:
            # Which fields changed decides which triggers fire. A workflow that
            # watches a file field and saves other fields on the same record
            # would otherwise re-trigger itself forever.
            changed = {
                k
                for k in set(old_data) | set(new_data)
                if old_data.get(k) != new_data.get(k)
            }
            runs = self._job_svc.trigger_for_record(
                named,
                "record_updated",
                changed_fields=changed,
                depth=_job_depth,
                changes={k: (old_data.get(k), new_data.get(k)) for k in changed},
                cause=_cause,
            )
            return named, len(runs)
        return named, 0

    # ------------------------------------------------------------------
    # Queries -- every read path (collection list, a record's descendants,
    # saved views, exports, counts, the AI tools) goes through RecordQuery
    # ------------------------------------------------------------------

    def resolve(self, query: RecordQuery) -> ResolvedQuery:
        """Names -> ids: the dataset, schema, `within`/parent records, the
        filter tree (each leaf located on the queried schema, an ancestor or
        a descendant) and the sort keys. Raises on anything that doesn't
        resolve, so a bad query fails loudly instead of matching nothing."""
        dataset_id = None
        if query.dataset:
            dataset = self._datasets.get_by_name(query.dataset, with_count=False)
            if not dataset:
                raise NotFoundError(f"Dataset '{query.dataset}' not found")
            dataset_id = dataset.id
        schema = self._schema_svc.get(query.schema) if query.schema else None

        parent_uuid = None
        if query.parent_record_id:
            parent = self._records.get_by_prefix(query.parent_record_id)
            if not parent:
                raise NotFoundError(
                    f"Parent record '{query.parent_record_id}' not found"
                )
            parent_uuid = parent.id

        within = beneath = None
        ancestor = self._records.get_by_prefix(query.within) if query.within else None
        if query.within and ancestor is None:
            raise NotFoundError(f"Record '{query.within}' not found")
        if ancestor is not None and schema is None:
            # Every kind beneath the record: as far down as its kinds go.
            below = self._schema_svc.descendants(
                self._schema_svc.get(ancestor.schema_name)
            )
            beneath = (ancestor.id, max((d for _, d in below), default=0))
        elif ancestor is not None and schema is not None:
            chain = self._schema_svc.ancestors(schema)
            hops = next(
                (i for i, a in enumerate(chain, start=1) if a.id == ancestor.schema_id),
                None,
            )
            if hops is None:
                raise ValidationError(
                    f"'{schema.name}' records can't descend from a "
                    f"'{ancestor.schema_name}' record"
                )
            within = (ancestor.id, hops)

        if query.where and schema is None:
            # A field's name means something only within its schema; without
            # one, `field=value` would quietly match nothing.
            raise ValidationError(
                "To filter by a field, also choose a schema. To match text in "
                "any field, search instead."
            )
        name_map = self._schema_svc.name_to_id_map(schema) if schema else {}
        field_filters: list[tuple[str, str]] = []
        for condition in query.where:
            if "=" not in condition:
                raise ValueError(f"Invalid filter '{condition}'. Use field=value.")
            key, _, value = condition.partition("=")
            field_filters.append((name_map.get(key, key), value))

        return ResolvedQuery(
            dataset_id=dataset_id,
            schema_id=schema.id if schema else None,
            parent_record_id=parent_uuid,
            within=within,
            beneath=beneath,
            field_filters=field_filters,
            search=self.text_search(query.search, schema, query.search_fields),
            filter_tree=self._resolve_filter(schema, query.filter_tree),
            created_after=query.created_after,
            created_before=query.created_before,
            sort=self._resolve_sort(schema, query.sort),
        )

    def text_search(
        self,
        term: str | None,
        schema: SchemaDTO | None = None,
        field_names: list[str] | None = None,
    ) -> TextSearch | None:
        """A search term resolved to the fields it looks in: the one rule
        behind the explorer, reference pickers, the jump-to box and the AI
        tools. Without `field_names` that is every searchable field of
        `schema`, or of every schema when there is none; with them, exactly
        those fields of `schema`. Only a kind's own fields: a record holds no
        value for a field it inherits (that is the record above's). A field of a type in
        `UNSEARCHED_DTYPES` (a reference, a boolean, a geometry) can't be
        searched. None when there is nothing to search for."""
        term = (term or "").strip()
        if not term:
            return None
        if field_names:
            if schema is None:
                raise ValidationError(
                    "To search one field, also choose a schema. To search "
                    "every field, leave the field out."
                )
            by_name = {f.name: f for f in schema.fields}
            ids = []
            for name in field_names:
                f = by_name.get(name)
                if f is None:
                    raise ValidationError(
                        f"'{schema.name}' has no field '{name}' of its own to "
                        "search (an inherited field's value is on the record "
                        "above: search that kind instead)"
                    )
                if f.dtype in UNSEARCHED_DTYPES:
                    raise ValidationError(
                        f"'{name}' is a {f.dtype} field and can't be searched"
                    )
                ids.append(str(f.id))
            return TextSearch(term, tuple(dict.fromkeys(ids)))
        if schema is not None:
            fields = list(schema.fields)
        else:
            fields = [f for s in self._schema_svc.list_all() for f in s.fields]
        return TextSearch(
            term,
            tuple(
                dict.fromkeys(
                    str(f.id) for f in fields if f.dtype not in UNSEARCHED_DTYPES
                )
            ),
        )

    def _relations(self, schema: SchemaDTO) -> dict[str, tuple[SchemaDTO, Relation]]:
        """Every schema a condition on `schema` may name, with where its
        records sit relative to `schema`'s: itself, then ancestors (nearest
        first), then descendants."""
        related: dict[str, tuple[SchemaDTO, Relation]] = {schema.name: (schema, SELF)}
        for hops, ancestor in enumerate(self._schema_svc.ancestors(schema), start=1):
            related[ancestor.name] = (ancestor, Relation("up", hops))
        for descendant, depth in self._schema_svc.descendants(schema):
            related[descendant.name] = (
                descendant,
                Relation("down", depth, descendant.id),
            )
        return related

    def _locate(
        self,
        schema: SchemaDTO,
        related: dict[str, tuple[SchemaDTO, Relation]],
        field_name: str,
        schema_name: str | None,
        what: str,
    ) -> tuple[FieldDTO, Relation]:
        """The field a condition/sort names, and its relation to `schema`.
        Unqualified names resolve on `schema` itself, else on the nearest
        ancestor that owns them (an inherited field lives on the parent
        record, not the child's own data). A formula can't be filtered or
        sorted by: the database holds no value for it to test."""
        f, rel = self._locate_field(schema, related, field_name, schema_name, what)
        if f.dtype in COMPUTED_DTYPES and what in ("filter", "sort"):
            raise ValidationError(
                f"'{f.name}' is a formula, worked out when read: a list can't be "
                f"{'filtered' if what == 'filter' else 'sorted'} by it"
            )
        return f, rel

    def _locate_field(
        self,
        schema: SchemaDTO,
        related: dict[str, tuple[SchemaDTO, Relation]],
        field_name: str,
        schema_name: str | None,
        what: str,
    ) -> tuple[FieldDTO, Relation]:
        if schema_name is None:
            for owner, rel in related.values():
                if rel.direction == "down":
                    break
                for f in owner.fields:
                    if f.name == field_name:
                        return f, rel
            raise ValidationError(
                f"Unknown {what} field '{field_name}' for schema '{schema.name}'"
            )
        entry = related.get(schema_name)
        if entry is None:
            raise ValidationError(
                f"Schema '{schema_name}' is neither '{schema.name}' nor one of "
                "its ancestors or descendants"
            )
        owner, rel = entry
        for f in owner.fields:
            if f.name == field_name:
                return f, rel
        raise ValidationError(
            f"Unknown {what} field '{field_name}' on schema '{schema_name}'"
        )

    def _resolve_filter(
        self, schema: SchemaDTO | None, tree: dict[str, Any] | None
    ) -> FilterNode | None:
        if tree is None:
            return None
        node = parse_filter_tree(tree)
        for leaf in leaves(node):
            if leaf.field == note_rules.OPEN_NOTES_FILTER:
                _check_open_notes_leaf(leaf)
        if schema is None:
            # A list of every kind: a field means something only within its
            # kind, so only what is about the record itself can be asked.
            for leaf in leaves(node):
                if leaf.field != note_rules.OPEN_NOTES_FILTER:
                    raise ValidationError(
                        f"To filter by '{leaf.field}', choose a kind of record "
                        "first: a field belongs to one kind. A list of every "
                        "kind can be filtered by whether it has open notes."
                    )
            return node
        related = self._relations(schema)

        def resolve_leaf(leaf: FilterCondition) -> FilterCondition:
            if leaf.field == note_rules.OPEN_NOTES_FILTER:
                return leaf  # about the record itself, not one of its fields
            f, rel = self._locate(schema, related, leaf.field, leaf.schema, "filter")
            return dataclasses.replace(leaf, field=str(f.id), rel=rel, dtype=f.dtype)

        return map_leaves(node, resolve_leaf)

    def _resolve_sort(
        self, schema: SchemaDTO | None, sort: list[dict[str, Any]] | None
    ) -> list[SortKey] | None:
        if not sort:
            return None
        related = self._relations(schema) if schema is not None else None
        keys = []
        for entry in sort:
            if not isinstance(entry, dict) or "field" not in entry:
                raise ValidationError(
                    "Each sort entry must be an object with a 'field' key"
                )
            direction = entry.get("direction", "asc")
            if direction not in ("asc", "desc"):
                raise ValidationError(
                    f"Invalid sort direction '{direction}': must be 'asc' or 'desc'"
                )
            if entry["field"] in META_SORTS and not entry.get("schema"):
                keys.append(
                    SortKey(
                        field_id="",
                        descending=direction == "desc",
                        meta=entry["field"],
                    )
                )
                continue
            if schema is None or related is None:
                raise ValidationError(
                    f"To sort by '{entry['field']}', choose a kind of record "
                    f"first. A list of every kind sorts by {', '.join(META_SORTS)}."
                )
            f, rel = self._locate(
                schema, related, entry["field"], entry.get("schema"), "sort"
            )
            if rel.direction == "down":
                raise ValidationError(
                    f"Can't sort by '{entry['field']}': a record can have many "
                    "descendants of that schema"
                )
            keys.append(
                SortKey(
                    field_id=str(f.id),
                    numeric=f.dtype in ("integer", "float"),
                    descending=direction == "desc",
                    rel=rel,
                )
            )
        return keys

    def preview_formula(
        self,
        schema_name: str,
        expression: str,
        *,
        result: str | None = None,
        decimals: int | None = None,
        field: str | None = None,
        record_id: str | None = None,
        values: dict[str, Any] | None = None,
    ) -> FormulaPreviewDTO:
        """What a formula on `schema_name` would give, saving nothing: checked
        as saving the field would (`SchemaService.check_formula`; `field` is the
        formula being edited, which can't read itself), then worked out for the
        record `record_id` (of that kind; fields above it and links are read as
        for any formula), or over `values` (by field name, as stored), or, with
        neither, the kind's most recently changed record. A formula that can't
        be saved comes back as `problem`, one that can't be worked out for that
        record as `error`: neither raises."""
        self._permissions.require_somewhere(permissions.READ)
        schema = self._schema_svc.get(schema_name)
        rules: dict[str, Any] = {"expression": expression}
        if result:
            rules["result"] = result
        if decimals is not None:
            rules["decimals"] = decimals
        try:
            rules = self._schema_svc.check_formula(schema_name, rules, field)
        except ValidationError as e:
            return FormulaPreviewDTO(problem=str(e))
        formula = formulas.parse(rules["expression"])
        record: RecordDTO | None = None
        if values is None:
            if record_id:
                record = self.get(record_id)
                if record.schema_id != schema.id:
                    raise ValidationError(
                        f"That record is a {record.schema_name}, not a {schema.name}"
                    )
            else:
                latest = self.recently_changed(schema_name, limit=1)
                record = latest[0] if latest else None
            if record is not None:
                values = {**record.data, **(record.derived or {})}
                outside = [n for n in formula.names if n not in values]
                if outside:
                    values.update(
                        self._derived_values(schema.name, [record], outside)[0]
                    )
        _, dtypes = self._schema_svc.formula_kinds(schema, leave_out=field)
        value, error = formulas.compute(
            formula,
            values or {},
            dtypes,
            rules["result"],
            rules.get("decimals"),
        )
        return FormulaPreviewDTO(
            value=value,
            error=error,
            result=rules["result"],
            record_id=record.id if record else None,
            record_name=record.natural_name if record else None,
        )

    def points(
        self,
        query: RecordQuery,
        field: str,
        schema: str | None = None,
        limit: int = POINTS_DEFAULT_LIMIT,
    ) -> RecordPoints:
        """Where the records `query` lists are, for a map: each one's id,
        name and the geometry in its `geo` field `field` (of the kind listed,
        or of `schema`, a kind above it, like a filter condition; the record
        above holds it then). Records with no value are left out; at most
        `limit`, oldest first, and `total` says how many have one. A fixed
        number of statements however many records."""
        self._permissions.require_somewhere(permissions.READ)
        if not 1 <= limit <= POINTS_MAX_LIMIT:
            raise ValidationError(f"The limit must be between 1 and {POINTS_MAX_LIMIT}")
        if not query.schema:
            raise ValidationError(
                "Choose the kind of record to map: a map shows one kind's "
                "location field"
            )
        resolved = self.resolve(query)
        listed = self._schema_svc.get(query.schema)
        related = self._relations(listed)
        f, rel = self._locate(listed, related, field, schema, "map")
        if rel.direction == "down":
            raise ValidationError(
                f"Can't map '{field}' of '{schema}': each record has many of "
                "those beneath it"
            )
        if f.dtype != "geo":
            raise ValidationError(f"'{f.name}' is not a location field")
        owner = next(s for s, r in related.values() if r == rel)
        found, total = self._records.geometries(resolved, str(f.id), rel.hops, limit)
        shapes = self._schema_svc.resolver()
        named = self._label_references(
            [self._with_names(r, shapes) for r, _ in found], shapes
        )
        return RecordPoints(
            schema=owner.name,
            field=f.name,
            points=[
                RecordPoint(r.id, r.natural_name, geometry)
                for r, (_, geometry) in zip(named, found)
            ],
            total=total,
            limit=limit,
        )

    def check_summary(self, schema_name: str, request: summary.SummaryRequest) -> None:
        """Whether `request` can summarise records of `schema_name`: its shape
        (`SummaryRequest.check`), and each grouping and measure a field of that
        kind or of a kind above it that allows it. The rule `summarise` runs
        first, without reading any record (a saved analysis is checked by it)."""
        request.check()
        self._summary_columns(schema_name, request, "UTC")

    def check_chart(self, schema_name: str, chart: Chart) -> None:
        """Whether `chart` can be drawn for records of `schema_name`, without
        reading any record: its bars by `check_summary`, a map's field a
        location field of the kind or of a kind above it."""
        if chart.summary is not None:
            self.check_summary(schema_name, chart.summary.request())
            return
        listed = self._schema_svc.get(schema_name)
        field, above = chart.map_field
        f, rel = self._locate(listed, self._relations(listed), field, above, "map")
        if rel.direction == "down" or f.dtype != "geo":
            raise ValidationError(f"'{chart.map}' is not a location field")

    def _summary_columns(
        self, schema_name: str, request: summary.SummaryRequest, zone_default: str
    ) -> tuple[
        list[summary.GroupPlan],
        list[summary.GroupColumn],
        list[summary.MeasurePlan],
        list[summary.MeasureColumn],
        str | None,
    ]:
        """The request's groupings and measures resolved against the kind's
        fields: what the repository is handed and how the columns read, and
        the zone dates and times are grouped in, if any."""
        schema = self._schema_svc.get(schema_name)
        related = self._relations(schema)
        owners = {rel: s for s, rel in related.values()}

        def locate(field: str, schema_name: str | None, what: str):
            f, rel = self._locate(schema, related, field, schema_name, what)
            if rel.direction == "down":
                raise ValidationError(
                    f"Can't {what} '{field}' of '{schema_name}': each record "
                    "has many of those beneath it"
                )
            owner = owners[rel]
            label = f.display_name
            if owner.id != schema.id:
                label = f"{owner.display_name} {label}"
            return f, rel.hops, owner.name, label

        group_plans: list[summary.GroupPlan] = []
        group_columns: list[summary.GroupColumn] = []
        zone_used: str | None = None
        for g in request.group_by:
            f, hops, owner, label = locate(g.field, g.schema, "group by")
            problem = summary.group_problem(g, f.dtype, f.name)
            if problem:
                raise ValidationError(problem)
            zone = None
            if f.dtype == "datetime" and g.bucket:
                zone = f.restrictions.get("timezone") or zone_default
                zone_used = zone
            group_plans.append(
                summary.GroupPlan(
                    summary.FieldPlan(str(f.id), f.dtype, hops),
                    bucket=g.bucket,
                    bin=g.bin,
                    zone=zone,
                    zone_offsets=offset_changes(zone) if zone else None,
                )
            )
            if g.bucket:
                label = f"{label} ({g.bucket})"
            group_columns.append(
                summary.GroupColumn(
                    key=g.key,
                    field=f.name,
                    schema=owner,
                    label=label,
                    dtype=f.dtype,
                    bucket=g.bucket,
                    bin=g.bin,
                    unit=f.restrictions.get("unit"),
                )
            )

        measure_plans: list[summary.MeasurePlan] = []
        measure_columns: list[summary.MeasureColumn] = []
        for m in request.measures:
            if m.field is None:
                measure_plans.append(summary.MeasurePlan("count"))
                measure_columns.append(
                    summary.MeasureColumn(m.key, "count", summary.MEASURES["count"])
                )
                continue
            if m.measure == summary.INSIDE:
                below = {
                    s.name: (s, depth)
                    for s, depth in self._schema_svc.descendants(schema)
                }
                if m.field not in below:
                    raise ValidationError(
                        f"'{m.field}' is not a kind of record beneath '{schema.name}'"
                    )
                child, depth = below[m.field]
                measure_plans.append(
                    summary.MeasurePlan(summary.INSIDE, child=(child.id, depth))
                )
                measure_columns.append(
                    summary.MeasureColumn(
                        key=m.key,
                        measure=summary.INSIDE,
                        label=f"{child.display_name} inside",
                        field=child.name,
                    )
                )
                continue
            f, hops, owner, label = locate(m.field, m.schema, "work out")
            problem = summary.measure_problem(m.measure, f.dtype, f.name)
            if problem:
                raise ValidationError(problem)
            measure_plans.append(
                summary.MeasurePlan(
                    m.measure, summary.FieldPlan(str(f.id), f.dtype, hops)
                )
            )
            unit = (
                f.restrictions.get("unit")
                if m.measure in summary.VALUE_MEASURES
                else None
            )
            measure_columns.append(
                summary.MeasureColumn(
                    key=m.key,
                    measure=m.measure,
                    label=summary.measure_label(m.measure, label),
                    field=f.name,
                    schema=owner,
                    dtype=f.dtype,
                    unit=unit,
                )
            )

        return group_plans, group_columns, measure_plans, measure_columns, zone_used

    def summarise(
        self, query: RecordQuery, request: summary.SummaryRequest
    ) -> summary.SummaryResult:
        """Group the records `query` lists by field values and work out
        measures over each group and over them all (see `domain/summary`).
        The query must name the kind summarised (`schema`); a grouping or a
        measure names one of its fields, or (`schema`) a field of a kind above
        it, like a filter condition. In SQL, one statement however many
        records; a link field's groups are named in one more lookup."""
        self._permissions.require_somewhere(permissions.READ)
        request.check()
        if not query.schema:
            raise ValidationError(
                "Choose the kind of record to summarise: a summary groups the "
                "values of one kind's fields"
            )
        resolved = self.resolve(query)
        zone_default = "UTC"
        if query.dataset:
            dataset = self._datasets.get_by_name(query.dataset, with_count=False)
            if dataset and dataset.timezone:
                zone_default = dataset.timezone

        group_plans, group_columns, measure_plans, measure_columns, zone_used = (
            self._summary_columns(query.schema, request, zone_default)
        )

        raw = self._records.summarise(
            resolved,
            summary.SummaryPlan(group_plans, measure_plans, request.limit),
        )

        # Records a link field's groups point at, named as everywhere else.
        linked = {
            str(r[i])
            for r in raw.rows
            for i, c in enumerate(group_columns)
            if c.dtype in ("reference", "reference_list") and r[i] is not None
        }
        names = (
            {
                str(r.id): r.natural_name or str(r.id)[:8]
                for r in self.labels(sorted(linked))
            }
            if linked
            else {}
        )

        def to_utc(zone: str):
            def convert(local_date: str) -> str:
                start = _dt.fromisoformat(local_date).replace(tzinfo=ZoneInfo(zone))
                return start.astimezone(timezone.utc).isoformat()

            return convert

        rows: list[summary.SummaryRow] = []
        width = len(group_columns)
        for r in raw.rows:
            groups = []
            conditions: list[dict[str, Any]] | None = []
            for i, (column, plan) in enumerate(zip(group_columns, group_plans)):
                value, where = summary.group_value(
                    column,
                    r[i],
                    each=plan.each,
                    names=names,
                    to_utc=to_utc(plan.zone) if plan.zone else None,
                )
                groups.append(value)
                if where is None:
                    conditions = None
                elif conditions is not None:
                    conditions.append(where)
            rows.append(
                summary.SummaryRow(
                    groups=groups,
                    values=[
                        summary.measure_value(c, v)
                        for c, v in zip(measure_columns, r[width:])
                    ],
                    where=(
                        None
                        if not conditions
                        else conditions[0]
                        if len(conditions) == 1
                        else {"and": conditions}
                    ),
                )
            )
        return summary.SummaryResult(
            schema=self._schema_svc.get(query.schema).name,
            group_columns=group_columns,
            measure_columns=measure_columns,
            rows=rows,
            total=[
                summary.measure_value(c, v) for c, v in zip(measure_columns, raw.total)
            ],
            truncated=raw.truncated,
            limit=request.limit,
            timezone=zone_used,
        )

    def query_records(
        self,
        query: RecordQuery,
        limit: int = 50,
        offset: int = 0,
        columns: list[str] | None = None,
        child_counts: bool = False,
        after: tuple[_dt, uuid.UUID] | None = None,
        as_stored: bool = False,
    ) -> list[RecordDTO]:
        """One page of `query`. `columns` asks for values that aren't in a
        record's own data (an inherited field, a `ref.field` join), attached
        as `derived`; `child_counts` attaches per-child-schema counts. `after`
        continues an unsorted listing past a record (see `stream_records`).
        `as_stored`: the records as they are kept (name-keyed), with none of
        the momentary extras, so reading them asks no drive where a file is."""
        records = self._records.list_filtered(
            self.resolve(query), offset, limit, after=after
        )
        return self._decorate(records, query, columns, child_counts, as_stored)

    def query_records_page(
        self,
        query: RecordQuery,
        limit: int = 50,
        cursor: str | None = None,
        columns: list[str] | None = None,
        child_counts: bool = False,
        as_stored: bool = False,
    ) -> RecordPage:
        """One page of `query` by keyset, sorted or not: `cursor` (the
        previous page's `next_cursor`, opaque) continues strictly after its
        last record, so a deep page costs what the first does and records
        added or removed between requests neither repeat nor skip. The page's
        `next_cursor` is None on the last page."""
        after_key: list[Any] | None = None
        if cursor:
            after_key, directions = decode_cursor(cursor)
        records, key, directions_now = self._records.list_keyset(
            self.resolve(query), limit, after_key
        )
        if cursor and directions != directions_now:
            raise ValidationError("The cursor does not belong to this query's sort")
        return RecordPage(
            self._decorate(records, query, columns, child_counts, as_stored),
            encode_cursor(key, directions_now) if key is not None else None,
        )

    def _decorate(
        self,
        records: list[RecordDTO],
        query: RecordQuery,
        columns: list[str] | None,
        child_counts: bool,
        as_stored: bool,
    ) -> list[RecordDTO]:
        if as_stored:
            return self._with_names_many(records)
        named = self._attach_open_notes(
            self._attach_reference_labels(self._with_names_many(records))
        )
        if columns and query.schema:
            named = self._attach_derived(query.schema, named, columns)
        if child_counts:
            counts = self._records.count_children([r.id for r in named])
            named = [
                dataclasses.replace(r, child_counts=counts.get(r.id, {})) for r in named
            ]
        return named

    def count_records(self, query: RecordQuery) -> int:
        return self._records.count(self.resolve(query))

    def estimate_records(self, query: RecordQuery) -> tuple[int, bool]:
        """(matching records, whether that is an estimate): the planner's on
        PostgreSQL, at no cost per record, exact elsewhere."""
        return self._records.estimate_count(self.resolve(query))

    def stream_records(
        self,
        query: RecordQuery,
        page_size: int = 500,
        columns: list[str] | None = None,
        as_stored: bool = False,
    ) -> Iterator[list[RecordDTO]]:
        """Every matching record, one page at a time -- for exports, which
        must not hold the whole result set in memory (`as_stored`: see
        `query_records`).

        Each page continues from the last record's sort key (a cursor, see
        `query_records_page`) rather than an ever-growing OFFSET, which would
        re-read every row it skips and make a large export quadratic."""
        cursor: str | None = None
        while True:
            page = self.query_records_page(
                query,
                limit=page_size,
                cursor=cursor,
                columns=columns,
                as_stored=as_stored,
            )
            if page.items:
                yield page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    def schema_counts(self, query: RecordQuery) -> dict[str, int]:
        """Matching records per schema name -- one GROUP BY, no rows loaded.
        With `within` and no schema, counts each descendant schema of that
        record's own (one grouped count per schema, not per record)."""
        if query.within and not query.schema:
            ancestor = self._records.get_by_prefix(query.within)
            if not ancestor:
                raise NotFoundError(f"Record '{query.within}' not found")
            counts: dict[str, int] = {}
            for descendant, _ in self._schema_svc.descendants(
                self._schema_svc.get(ancestor.schema_name)
            ):
                n = self.count_records(query.for_kind(descendant.name))
                if n:
                    counts[descendant.name] = n
            return counts
        return self._records.count_by_schema(self.resolve(query))

    # Keyword-argument conveniences over the methods above, for callers that
    # think in "a collection, maybe one schema" (CLI, plugins, AI tools).

    def find(
        self,
        dataset_name: str,
        schema_name: str | None = None,
        parent_record_id: str | None = None,
        filters: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        search_fields: list[str] | None = None,
    ) -> list[RecordDTO]:
        return self.query_records(
            RecordQuery(
                dataset=dataset_name,
                schema=schema_name,
                parent_record_id=parent_record_id,
                where=filters or [],
                filter_tree=filter_tree,
                search=search,
                search_fields=search_fields,
            ),
            limit=limit,
            offset=offset,
        )

    def count(
        self,
        dataset_name: str,
        schema_name: str | None = None,
        parent_record_id: str | None = None,
        filters: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        search: str | None = None,
        search_fields: list[str] | None = None,
    ) -> int:
        return self.count_records(
            RecordQuery(
                dataset=dataset_name,
                schema=schema_name,
                parent_record_id=parent_record_id,
                where=filters or [],
                filter_tree=filter_tree,
                search=search,
                search_fields=search_fields,
            )
        )

    def iter_find(
        self,
        dataset_name: str,
        schema_name: str | None = None,
        parent_record_id: str | None = None,
        filters: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        search: str | None = None,
        page_size: int = 500,
        search_fields: list[str] | None = None,
    ) -> Iterator[list[RecordDTO]]:
        return self.stream_records(
            RecordQuery(
                dataset=dataset_name,
                schema=schema_name,
                parent_record_id=parent_record_id,
                where=filters or [],
                filter_tree=filter_tree,
                search=search,
                search_fields=search_fields,
            ),
            page_size=page_size,
        )

    def count_by_schema_search(
        self,
        schema_name: str,
        search: str | None = None,
        search_fields: list[str] | None = None,
    ) -> int:
        """Total matching `find_by_schema` -- same predicate, in SQL."""
        schema = self._schema_svc.get(schema_name)
        return self._records.count_schema_matches(
            schema.id, search=self.text_search(search, schema, search_fields)
        )

    def find_by_schema(
        self,
        schema_name: str,
        search: str | None = None,
        limit: int = 20,
        reachable_from: str | None = None,
        search_fields: list[str] | None = None,
    ) -> list[RecordDTO]:
        """`reachable_from` (a collection name) limits the search to records a
        record in that collection may reference: its own collection's plus
        those of global collections (civex.domain.scopes). What a reference
        picker searches, so it never offers another local collection's
        records."""
        schema = self._schema_svc.get(schema_name)
        dataset_ids = None
        if reachable_from:
            source = self._datasets.get_by_name(reachable_from, with_count=False)
            if not source:
                raise NotFoundError(f"Dataset '{reachable_from}' not found")
            dataset_ids = [source.id] + [
                d.id
                for d in self._datasets.list_all(with_count=False)
                if d.scope == GLOBAL and d.id != source.id
            ]
        records = self._records.list_by_schema(
            schema.id,
            search=self.text_search(search, schema, search_fields),
            limit=limit,
            dataset_ids=dataset_ids,
        )
        return self._attach_reference_labels(self._with_names_many(records))

    def search(
        self,
        query: str,
        limit: int = 20,
        collection: str | None = None,
    ) -> list[RecordDTO]:
        """Records of any schema matching `query`, best match first -- what a
        jump-to box searches. Every collection unless `collection` (a name)
        narrows it; each result carries its collection's name, since the same
        schema's records can live in several."""
        search = self.text_search(query)
        if search is None:
            return []
        dataset_id = None
        if collection:
            dataset = self._datasets.get_by_name(collection, with_count=False)
            if not dataset:
                raise NotFoundError(f"Dataset '{collection}' not found")
            dataset_id = dataset.id
        records = self._records.search_all(search, limit=limit, dataset_id=dataset_id)
        return self._attach_reference_labels(self._with_names_many(records))

    # ------------------------------------------------------------------
    # Columns that aren't in a record's own data
    # ------------------------------------------------------------------

    def validate_columns(self, schema: SchemaDTO, columns: list[str]) -> None:
        """Every column must be a field of `schema` (own or inherited), a
        single-hop `ref_field.target_field` join through a reference field, or
        `@open_notes` (the record's open threads of notes, a column of the
        explorer)."""
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schema_svc.collect_fields(schema)
        }
        unknown = []
        for col in columns:
            if col == note_rules.OPEN_NOTES_FILTER:
                continue  # shown from `open_notes`/`latest_note`, not `data`
            if "." in col:
                self._validate_join_column(col, fields_by_name)
            elif col not in fields_by_name:
                unknown.append(col)
        if unknown:
            raise ValidationError(
                f"Unknown column field(s) {sorted(unknown)} for this schema"
            )

    def _validate_join_column(
        self, col: str, fields_by_name: dict[str, FieldDTO]
    ) -> None:
        parts = col.split(".")
        if len(parts) != 2:
            raise ValidationError(
                f"Column '{col}' is not a valid reference-field join -- only "
                "one hop is supported (e.g. 'customer.email')"
            )
        ref_name, target_name = parts
        ref_field = fields_by_name.get(ref_name)
        if ref_field is None:
            raise ValidationError(
                f"Unknown column field(s) ['{ref_name}'] for this schema"
            )
        if ref_field.dtype != "reference":
            raise ValidationError(
                f"Column '{col}' joins through '{ref_name}', a '{ref_field.dtype}' "
                "field -- only single 'reference' fields support joins"
            )
        target_schema_name = ref_field.restrictions.get("schema")
        if not target_schema_name:
            raise ValidationError(
                f"Column '{col}' joins through '{ref_name}', which has no target "
                "schema restriction set"
            )
        try:
            target_schema = self._schema_svc.get(target_schema_name)
        except NotFoundError:
            raise ValidationError(
                f"Column '{col}' targets schema '{target_schema_name}', which "
                "does not exist"
            ) from None
        target_known = {
            rf.field.name for rf in self._schema_svc.collect_fields(target_schema)
        }
        if target_name not in target_known:
            raise ValidationError(
                f"Unknown column field(s) ['{col}'] for schema '{target_schema_name}'"
            )

    def with_derived(
        self, schema_name: str, records: list[RecordDTO], columns: list[str]
    ) -> list[RecordDTO]:
        """`records` (all of one schema) with `derived` filled for `columns`: the
        fields a record's own data can't answer (inherited from an ancestor,
        `ref.field` joins). For a table made from records already in hand."""
        return self._attach_derived(schema_name, records, columns)

    def _attach_derived(
        self, schema_name: str, records: list[RecordDTO], columns: list[str]
    ) -> list[RecordDTO]:
        """Fill `derived` with the requested columns a record's own data
        can't answer (see `_derived_values`)."""
        # A record read for the API already has its own formulas worked out.
        columns = [
            c for c in columns if not all(c in (r.derived or {}) for r in records)
        ]
        values = self._derived_values(schema_name, records, columns)
        if not any(values):
            return records
        return [
            dataclasses.replace(record, derived={**(record.derived or {}), **derived})
            for record, derived in zip(records, values)
        ]

    def _derived_values(
        self, schema_name: str, records: list[RecordDTO], columns: list[str]
    ) -> list[dict[str, Any]]:
        """Per record (all of one schema, name-keyed), the requested columns its
        own data can't answer: fields inherited from an ancestor record, and
        `ref_field.target_field` joins (the reference may itself be inherited).
        Ancestors and join targets are each batch-loaded once per level, not
        once per row. A column that no longer resolves (a field or target
        schema renamed after a view was saved) is left out rather than raised
        -- this runs at read time, long after create/update validation."""
        try:
            schema = self._schema_svc.get(schema_name)
        except NotFoundError:
            return [{} for _ in records]
        related = self._relations(schema)
        own = {f.name for f in schema.fields}
        own_formulas = [
            c
            for c in columns
            if any(f.name == c and f.dtype in COMPUTED_DTYPES for f in schema.fields)
        ]
        # Formulas of the records above, by the schema that has them.
        above: dict[uuid.UUID, list[tuple[str, FieldDTO, int]]] = {}
        located_fields: dict[str, FieldDTO] = {}

        def plain(name: str) -> tuple[str, int] | None:
            """(field id, hops up) for a non-dotted column, None if unknown."""
            try:
                f, rel = self._locate(schema, related, name, None, "column")
            except ValidationError:
                return None
            located_fields[name] = f
            return str(f.id), rel.hops

        plans: dict[str, Any] = {}
        for col in columns:
            if "." in col:
                ref_name, _, target_name = col.partition(".")
                ref = plain(ref_name)
                ref_field = next(
                    (
                        rf.field
                        for rf in self._schema_svc.collect_fields(schema)
                        if rf.field.name == ref_name
                    ),
                    None,
                )
                target_schema_name = (
                    ref_field.restrictions.get("schema")
                    if ref_field and ref_field.dtype == "reference"
                    else None
                )
                if ref is None or not target_schema_name:
                    continue
                try:
                    target_schema = self._schema_svc.get(target_schema_name)
                except NotFoundError:
                    continue
                target_id = self._schema_svc.name_to_id_map(target_schema).get(
                    target_name
                )
                if target_id is not None:
                    plans[col] = ("join", ref, target_id)
            elif col not in own and (located := plain(col)) is not None:
                f = located_fields[col]
                if f.dtype in COMPUTED_DTYPES:
                    above.setdefault(f.schema_id, []).append((col, f, located[1]))
                plans[col] = ("inherited", located)
        computed = (
            dict(
                zip(
                    (str(r.id) for r in records),
                    self._formula_results(schema, records, own_formulas),
                )
            )
            if own_formulas and records
            else {}
        )
        if not plans:
            return [
                {c: v for c, (v, _) in computed.get(str(r.id), {}).items()}
                for r in records
            ]

        chains = self._ancestor_chains(records, max(p[1][1] for p in plans.values()))
        # An inherited formula is worked out on the record above that has it.
        worked_above: dict[tuple[str, uuid.UUID], Any] = {}
        for owner_id, wanted in above.items():
            owner = self._schema_svc.get_by_id(owner_id)
            if owner is None:
                continue
            holders: dict[uuid.UUID, RecordDTO] = {}
            for col, f, hops in wanted:
                for r in records:
                    a = chains[r.id][hops - 1] if hops else None
                    if a is not None and a.schema_id == owner_id:
                        holders.setdefault(a.id, a)
            named = self._with_names_many(list(holders.values()))
            results = self._formula_results(
                owner, named, list(dict.fromkeys(f.name for _, f, _ in wanted))
            )
            for a, found in zip(named, results):
                for name, (worked, _) in found.items():
                    worked_above[(name, a.id)] = worked
        id_to_name = self._schema_svc.id_to_name_map(schema)

        formula_names = {
            str(f.id): f.name for wanted in above.values() for _, f, _ in wanted
        }

        def value(record: RecordDTO, located: tuple[str, int]) -> Any:
            field_id, hops = located
            if hops == 0:
                return record.data.get(id_to_name[field_id])
            ancestor = chains[record.id][hops - 1]
            if ancestor is None:
                return None
            if field_id in formula_names:
                return worked_above.get((formula_names[field_id], ancestor.id))
            return ancestor.data.get(field_id)

        ref_values: dict[str, list[Any]] = {}
        for col, plan in plans.items():
            if plan[0] == "join":
                ref_values[col] = [value(r, plan[1]) for r in records]
        target_ids = {
            uuid.UUID(v)
            for values in ref_values.values()
            for v in values
            if isinstance(v, str) and _is_uuid(v)
        }
        targets = {t.id: t for t in self._records.list_by_ids(list(target_ids))}

        out = []
        for i, record in enumerate(records):
            derived: dict[str, Any] = {
                c: v for c, (v, _) in computed.get(str(record.id), {}).items()
            }
            for col, plan in plans.items():
                if plan[0] == "inherited":
                    derived[col] = value(record, plan[1])
                else:
                    ref_value = ref_values[col][i]
                    target = (
                        targets.get(uuid.UUID(ref_value))
                        if isinstance(ref_value, str) and _is_uuid(ref_value)
                        else None
                    )
                    derived[col] = target.data.get(plan[2]) if target else None
            out.append(derived)
        return out

    def _ancestor_chains(
        self, records: list[RecordDTO], levels: int
    ) -> dict[uuid.UUID, list[RecordDTO | None]]:
        """Per record, its parent, grandparent, ... (`levels` deep; None once
        the chain ends) -- one batched lookup per level for the whole page."""
        chains: dict[uuid.UUID, list[RecordDTO | None]] = {r.id: [] for r in records}
        current = {r.id: r.parent_record_id for r in records}
        for _ in range(levels):
            wanted = {p for p in current.values() if p}
            found = (
                {a.id: a for a in self._records.list_by_ids(list(wanted))}
                if wanted
                else {}
            )
            following: dict[uuid.UUID, uuid.UUID | None] = {}
            for rid, pid in current.items():
                ancestor = found.get(pid) if pid else None
                chains[rid].append(ancestor)
                following[rid] = ancestor.parent_record_id if ancestor else None
            current = following
        return chains

    def ancestors(self, record: RecordDTO) -> list[RecordDTO]:
        """The record's parent chain, root first -- the breadcrumb trail."""
        chain: list[RecordDTO] = []
        current = record
        while current.parent_record_id:
            parent = self._records.get_by_id(current.parent_record_id)
            if parent is None:
                break
            chain.append(self._with_names(parent))
            current = parent
        chain.reverse()
        return chain

    def ancestor_trails(
        self, records: list[RecordDTO]
    ) -> dict[uuid.UUID, list[RecordDTO]]:
        """Each record's parent chain, root first and named (so a caller can show
        or build a path from it) -- `ancestors` for a whole batch, with one
        lookup per level of the hierarchy instead of one per record."""
        known: dict[uuid.UUID, RecordDTO] = {}
        pending = {r.parent_record_id for r in records if r.parent_record_id}
        for _ in range(_MAX_TRAIL_DEPTH):
            wanted = [p for p in pending if p not in known]
            if not wanted:
                break
            found = self._records.list_by_ids(wanted)
            known.update({a.id: a for a in found})
            pending = {a.parent_record_id for a in found if a.parent_record_id}
        shapes = self._schema_svc.resolver()
        named = {
            a.id: a
            for a in self._label_references(
                [self._with_names(a, shapes) for a in known.values()], shapes
            )
        }
        trails: dict[uuid.UUID, list[RecordDTO]] = {}
        for r in records:
            chain: list[RecordDTO] = []
            parent = r.parent_record_id
            while parent and parent in named and len(chain) < _MAX_TRAIL_DEPTH:
                chain.append(named[parent])
                parent = named[parent].parent_record_id
            trails[r.id] = chain[::-1]
        return trails

    def beneath(
        self,
        records: list[RecordDTO],
        on_level: Callable[[int], None] | None = None,
        keep: Callable[[RecordDTO], bool] | None = None,
        as_stored: bool = False,
    ) -> list[RecordDTO]:
        """Every live record beneath these (children, their children, and so on),
        in the full response form, found a level at a time: a few queries for the
        whole set however many records there are, not one per record. The given
        records themselves are not repeated. `on_level` is told how many have
        been found after each level. `keep` (asked of each record as stored)
        returns only those it accepts: every level is still walked, but only
        those are named and labelled, the costly part."""
        seen = {r.id for r in records}
        frontier = [r.id for r in records]
        found: list[RecordDTO] = []
        shapes = self._schema_svc.resolver()
        for _ in range(_MAX_TRAIL_DEPTH):
            kids = [
                k for k in self._records.list_children_of(frontier) if k.id not in seen
            ]
            if not kids:
                break
            seen.update(k.id for k in kids)
            frontier = [k.id for k in kids]
            if keep is not None:
                kids = [k for k in kids if keep(k)]
            named = [self._with_names(k, shapes) for k in kids]
            # `as_stored`: as kept (no labels or file locations looked up).
            found.extend(
                named if as_stored else self._attach_reference_labels(named, shapes)
            )
            if on_level:
                on_level(len(found))
        return found

    def recently_changed(self, schema_name: str, limit: int = 5) -> list[RecordDTO]:
        """The live records of this schema changed most recently, newest
        first, at most `limit`: samples to try a workflow on."""
        schema = self._schema_svc.get(schema_name)
        return self.get_many(self._records.recently_changed(schema.id, limit))

    def get_many(
        self, record_ids: list[str], as_stored: bool = False
    ) -> list[RecordDTO]:
        """These live records in the order asked, in the full response form
        (names, reference labels, where each file is stored), in a fixed number
        of queries. Ids that aren't live records are left out. `as_stored`: as
        they are kept (see `query_records`)."""
        ids: list[uuid.UUID] = []
        for raw in dict.fromkeys(record_ids):
            try:
                ids.append(uuid.UUID(raw))
            except (ValueError, AttributeError, TypeError):
                continue
        found = {r.id: r for r in self._records.list_by_ids(ids) if not r.deleted_at}
        shapes = self._schema_svc.resolver()
        named = [self._with_names(found[i], shapes) for i in ids if i in found]
        if as_stored:
            return named
        return self._attach_reference_labels(named, shapes)

    def _resolve_set(self, picked: RecordSet) -> ResolvedSet:
        """Names -> ids for a set of records. A query that asks `listed` what
        a kind it can't be asked of lists (the filter means nothing there)
        lists nothing; ids that name no record are left out."""
        listed: list[ResolvedQuery] | None = None
        if picked.listed is not None:
            listed = []
            for query in picked.listed:
                try:
                    listed.append(self.resolve(query))
                except ValidationError:
                    continue
        ids: list[uuid.UUID] = []
        for raw in dict.fromkeys(picked.ids):
            try:
                ids.append(uuid.UUID(str(raw)))
            except (ValueError, AttributeError, TypeError):
                continue
        return ResolvedSet(
            queries=[self.resolve(q) for q in picked.queries],
            ids=ids,
            below=picked.below,
            listed=listed,
            schema_ids=(
                [s.id for s in self._schema_svc.list_all() if s.name in picked.kinds]
                if picked.kinds is not None
                else None
            ),
        )

    def held_files(
        self, picked: RecordSet, search: str | None = None
    ) -> list[HeldFile]:
        """Every file the set's records hold, as each is written in its record
        and with the copy that record points at: read by the database alone,
        in one statement however many records there are. Nothing is named and
        no drive is asked (a caller names the few it shows). `search` marks
        the files it finds (`HeldFile.found`): by the name a file was added
        under, or by its record, or one above it, as a search of records
        would find it."""
        schemas = self._schema_svc.list_all()
        file_fields = {
            str(f.id): f.name
            for s in schemas
            for f in s.fields
            if f.dtype in ("file", "file_list")
        }
        parent = {s.id: s.parent_id for s in schemas}
        depth = 0
        for start in parent:
            hops, at = 0, parent.get(start)
            while at is not None and hops < _MAX_TRAIL_DEPTH:
                hops, at = hops + 1, parent.get(at)
            depth = max(depth, hops)
        looked_for = self.text_search(search) if search else None
        if looked_for is not None:
            # A file is found by its own name, not by the name of another
            # file its record (or a record above) holds.
            looked_for = TextSearch(
                looked_for.term,
                tuple(i for i in looked_for.field_ids if i not in file_fields),
            )
        return self._records.held_files(
            self._resolve_set(picked),
            file_fields,
            looked_for,
            depth,
            following=self.files_from_server(),
        )

    def holding_files(self, picked: RecordSet) -> list[str]:
        """The ids of the set's records that hold a file, in the order records
        are listed: from the catalog, one statement. What a plan of files has
        to read, instead of every record of the set."""
        return [record_key(r) for r in self._records.holders(self._resolve_set(picked))]

    def shared_copies(self) -> dict[tuple[str, str | None], int]:
        """The copies of files, (sha256, volume), that more than one live
        record points at, and how many do. From the catalog, one statement."""
        return self._records.shared_copies()

    def file_values(
        self, records: list[RecordDTO], field_names: list[str] | None = None
    ) -> tuple[list[tuple[RecordDTO, str, dict[str, Any]]], set[str]]:
        """Every file held by `records`, as (record, field name, file value) in
        record then field order -- a `file_list` contributes one per file. Only
        the named fields when `field_names` is given. Also returns the names of
        all file fields the records' schemas have, so a caller can tell "no
        files" from "no such field"."""
        shapes = self._schema_svc.resolver()
        wanted = set(field_names) if field_names is not None else None
        known: set[str] = set()
        out: list[tuple[RecordDTO, str, dict[str, Any]]] = []
        for r in records:
            shape = shapes(r.schema_id)
            if shape is None:
                continue
            for rf in shape.fields:
                name = rf.field.name
                if rf.field.dtype not in ("file", "file_list"):
                    continue
                known.add(name)
                if wanted is not None and name not in wanted:
                    continue
                out.extend(
                    (r, name, ref)
                    for ref in _file_dicts(r.data.get(name))
                    if ref.get("sha256")
                )
        return out, known

    def delete(self, record_id: str, force: bool = False) -> None:
        record = self.get(record_id)
        self.apply_changes(RecordChangesDTO(delete=[record.id]), force=force)

    def delete_many(self, record_ids: list[str], force: bool = False) -> int:
        """Delete the records `record_ids` name (full ids or unique prefixes);
        ids that are missing or already deleted are skipped."""
        full: list[uuid.UUID] = []
        for rid in record_ids:
            try:
                full.append(uuid.UUID(rid))
            except ValueError:
                record = self._records.get_by_prefix(rid)
                if record:
                    full.append(record.id)
        live = [r.id for r in self._records.list_by_ids(full) if r.deleted_at is None]
        return self.apply_changes(RecordChangesDTO(delete=live), force=force).deleted

    def delete_matching(self, query: RecordQuery, force: bool = False) -> int:
        """Delete every record `query` matches -- what "select all N
        matching" means, as opposed to deleting the ids on one page."""
        return self.apply_changes(
            RecordChangesDTO(delete=self._records.list_ids(self.resolve(query))),
            force=force,
        ).deleted

    def delete_all(
        self, dataset_name: str, schema_name: str | None = None, force: bool = False
    ) -> int:
        return self.delete_matching(
            RecordQuery(dataset=dataset_name, schema=schema_name), force
        )

    def apply_changes(
        self,
        changes: RecordChangesDTO,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> RecordChangesResultDTO:
        """The one way a set of record changes is applied, whatever its size:
        bulk delete, bulk edit's undo, restore and the undo of any bulk action
        are all a `RecordChangesDTO` (what to restore, what to put back, what
        to delete). Each part is planned in memory from the few columns it
        needs and written a chunk at a time (a fixed number of statements per
        chunk, never one per record), and the history entries are written with
        it, in the order the changes must be applied, as one batch (the
        caller's) and one action. Permissions are checked for every collection
        touched before that part is written. What can't be applied is left as
        it is and reported; a record already as wanted (restored, or deleted)
        is counted as `unchanged`. With `dry_run` the restore and delete parts
        are planned and counted, nothing is written."""
        out = RecordChangesResultDTO()

        def leave(record_id: uuid.UUID, reason: str) -> None:
            out.left_count += 1
            if len(out.left) < MAX_REPORTED:
                out.left[record_id] = reason

        with nullcontext():
            if changes.restore:
                done = self.restore_set(changes.restore, dry_run=dry_run)
                out.restored, out.came_back = done.restored, done.came_back
                self._note_absent(
                    [uuid.UUID(r) for r in done.absent], out, leave, "already back"
                )
                for raw in done.left:
                    leave(
                        uuid.UUID(raw),
                        "Something it belongs to is still deleted, or its unique "
                        "values were taken meanwhile.",
                    )
            if changes.update and not dry_run:
                chunk = self._update_chunk(changes.update, unset=True)
                out.updated, out.runs = chunk.changing, chunk.runs
                for record_id in chunk.gone:
                    leave(record_id, "This record no longer exists, or is deleted.")
                for record_id, reason in chunk.failed.items():
                    leave(record_id, reason)
            if changes.delete:
                states = self._records.deleted_at_of(changes.delete)
                live = [
                    i for i in dict.fromkeys(changes.delete) if states.get(i, 1) is None
                ]
                self._note_absent(
                    [
                        i
                        for i in dict.fromkeys(changes.delete)
                        if states.get(i, 1) is not None
                    ],
                    out,
                    leave,
                    "already deleted",
                    states=states,
                )
                out.deleted_asked = len(live)
                if live:
                    out.deleted = self._delete_records(live, force, dry_run)
        return out

    def _note_absent(
        self,
        ids: list[uuid.UUID],
        out: RecordChangesResultDTO,
        leave: Callable[[uuid.UUID, str], None],
        why: str,
        states: dict[uuid.UUID, Any] | None = None,
    ) -> None:
        """Records asked to change that were not in the state the change starts
        from: counted as unchanged when they exist (already as wanted: `why`),
        left when they are gone altogether."""
        if not ids:
            return
        if states is None:
            states = self._records.deleted_at_of(ids)
        for rid in ids:
            if rid in states:
                out.unchanged += 1
            else:
                leave(rid, "This record no longer exists.")

    def _delete_records(
        self, ids: list[uuid.UUID], force: bool, dry_run: bool = False
    ) -> int:
        """Delete `ids` and everything beneath them. Returns how many of `ids`
        were deleted in their own right -- one already beneath another is
        deleted with it, and not counted again.

        The whole subtree is found a level at a time and soft-deleted, with its
        history entries, a chunk of records at a time: a bulk UPDATE and one
        insert statement per chunk, not a query and a flush per record."""
        levels = self._records.subtree_levels(ids, deleted=False)
        if not levels:
            return 0
        every = [rid for level in levels for rid in level]
        doomed = set(every)
        for dataset_id in self._records.collections_of(every):
            self._permissions.require(permissions.DELETE, dataset_id)
        self._handle_referrers(doomed, force, dry_run)
        if dry_run:  # every check made, nothing written
            links = self._records.parent_links(every)
            return sum(
                1 for rid in set(ids) if rid in links and links[rid] not in doomed
            )
        # One instant: it is the entries' time and what the records are stamped
        # with, so every device that applies these entries stamps them alike.
        stamp = _dt.now(timezone.utc)
        links = self._records.parent_links(every)
        # Each tree is one action: a record and everything beneath it go
        # together or not at all (a child left live under a deleted parent
        # is not a project), but separate trees deleted at once don't.
        ops = _tree_ops(links) if self._audit else None
        with _audit_batch(self._audit, "delete", len(every) > 1):
            for start in range(0, len(every), _APPLY_CHUNK):
                chunk = every[start : start + _APPLY_CHUNK]
                if self._audit:
                    held = {r.id: r for r in self._records.list_by_ids(chunk)}
                    self._audit.log_changes(
                        "delete",
                        "record",
                        (
                            (i, self._snapshot(held[i]), None)
                            for i in chunk
                            if i in held
                        ),
                        timestamp=stamp,
                        ops=ops,
                    )
                self._records.delete_many(chunk, stamp)
        return sum(1 for rid in set(ids) if rid in links and links[rid] not in doomed)

    def list_deleted(
        self,
        dataset_name: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[RecordDTO]:
        dataset_id = None
        if dataset_name:
            dataset = self._datasets.get_by_name(dataset_name, with_count=False)
            if not dataset:
                raise NotFoundError(f"Dataset '{dataset_name}' not found")
            dataset_id = dataset.id
        return self._attach_reference_labels(
            self._with_names_many(
                self._records.list_deleted(dataset_id, offset=offset, limit=limit)
            )
        )

    # ------------------------------------------------------------------
    # Moving records to another collection (or under another record)
    # ------------------------------------------------------------------

    def plan_move(
        self,
        to: str,
        parent: str | None = None,
        *,
        ids: list[str] | None = None,
        query: RecordQuery | None = None,
    ) -> RecordMovePlanDTO:
        """What moving the chosen records (`ids`, or every record `query`
        lists) to collection `to` would do, without doing it: how many go,
        with everything beneath them, and anything in the way. The one rule
        behind the preview and `move`, so they can't disagree."""
        return self._move_plan(to, parent, ids=ids, query=query)[0]

    def move(
        self,
        to: str,
        parent: str | None = None,
        *,
        ids: list[str] | None = None,
        query: RecordQuery | None = None,
    ) -> RecordMoveResultDTO:
        """Re-point the chosen records at collection `to`, inside `parent`
        there (or at its top level), with everything beneath them. A record
        keeps its id, its values and its history: this is a change to where
        it is, logged as an edit of each record moved (one action per tree,
        one event for the lot), so it is undoable from Activity and syncs like
        any other edit. Files are not copied anywhere: they are stored by
        content, not by collection. Refuses (`ValidationError`) with the plan's
        problems rather than doing part of it."""
        plan, roots, records, target = self._move_plan(to, parent, ids=ids, query=query)
        if plan.problems:
            raise ValidationError(" ".join(plan.problems))
        if not records:
            return RecordMoveResultDTO(roots=0, records=0, collection=target.name)
        stamp = _dt.now(timezone.utc)
        root_ids = {r.id for r in roots}
        if self._audit:
            tree = _tree_actions(records)
            with _audit_batch(self._audit, "move", len(records) > 1):
                for record in records:
                    after = dataclasses.replace(
                        record,
                        dataset_id=target.id,
                        parent_record_id=(
                            plan.parent_id
                            if record.id in root_ids
                            else record.parent_record_id
                        ),
                        updated_at=stamp,
                    )
                    self._audit.log_change(
                        "update",
                        "record",
                        record.id,
                        self._snapshot(record),
                        self._snapshot(after),
                        timestamp=stamp,
                        op=tree[record.id],
                    )
        self._records.move(
            [r.id for r in records], target.id, list(root_ids), plan.parent_id, stamp
        )
        return RecordMoveResultDTO(
            roots=len(roots), records=len(records), collection=target.name
        )

    def _move_plan(
        self,
        to: str,
        parent: str | None,
        *,
        ids: list[str] | None,
        query: RecordQuery | None,
    ) -> tuple[RecordMovePlanDTO, list[RecordDTO], list[RecordDTO], DatasetDTO]:
        """The plan, the roots that would move, every record that would (roots
        first, then the levels beneath, deleted descendants included: a
        child can't stay behind in another collection than its parent) and the
        target collection."""
        target = self._datasets.get_by_name(to, with_count=False)
        if target is None:
            raise NotFoundError(f"Collection '{to}' not found")
        above: RecordDTO | None = None
        if parent:
            above = self._records.get_by_prefix(parent)
            if above is None:
                raise NotFoundError(f"Record '{parent}' not found")
            if above.dataset_id != target.id:
                raise ValidationError(
                    f"'{self._deleted_name(above)}' is not in collection '{to}'"
                )
        parent_id = above.id if above else None
        self._permissions.require(permissions.WRITE_RECORDS, target.id)

        chosen = self._chosen_records(ids, query)
        # Already where they would go: nothing to do for them.
        roots = [
            r
            for r in chosen
            if not (r.dataset_id == target.id and r.parent_record_id == parent_id)
        ]
        skipped = len(chosen) - len(roots)
        levels = self._records.subtree_levels([r.id for r in roots], deleted=None)
        every = [rid for level in levels for rid in level]
        moving = set(every)
        # A record chosen along with one above it moves with that one.
        roots = [r for r in roots if r.parent_record_id not in moving]
        by_id = {r.id: r for r in self._records.list_by_ids(every)}
        records = [by_id[rid] for rid in every if rid in by_id]
        self._require_each(permissions.DELETE, records)
        sources = sorted(
            {
                d.name
                for did in {r.dataset_id for r in records}
                if (d := self._datasets.get_by_id(did, with_count=False)) is not None
                and d.id != target.id
            }
        )
        problems: list[str] = []
        if above is not None and above.id in moving:
            problems.append("A record can't be moved inside itself.")
        problems += self._move_kind_problems(roots, above)
        problems += self._move_reference_problems(records, moving, target)
        problems += self._move_unique_problems(roots, target, parent_id)
        plan = RecordMovePlanDTO(
            collection=target.name,
            collection_id=target.id,
            parent_id=parent_id,
            parent_name=self._deleted_name(above) if above else None,
            roots=len(roots),
            records=len(records),
            skipped=skipped,
            sources=sources,
            problems=problems,
        )
        return plan, roots, records, target

    def _chosen_records(
        self, ids: list[str] | None, query: RecordQuery | None
    ) -> list[RecordDTO]:
        """The live records a person picked: by id (full or prefix), or every
        one a query lists."""
        found = self._records.list_by_ids(self._chosen_ids(ids, query, "move"))
        return [r for r in found if r.deleted_at is None]

    def _chosen_ids(
        self, ids: list[str] | None, query: RecordQuery | None, verb: str
    ) -> list[uuid.UUID]:
        """The ids of the records a person picked, in order: exactly `ids`
        (full or prefix), or every record `query` lists. The one reading of
        "these, or all N matching" behind a move and a bulk edit. Deleted
        records may be among them: the caller leaves them out as it loads."""
        if ids is not None:
            full: list[uuid.UUID] = []
            for rid in ids:
                try:
                    full.append(uuid.UUID(rid))
                except ValueError:
                    record = self._records.get_by_prefix(rid)
                    if record:
                        full.append(record.id)
            return list(dict.fromkeys(full))
        if query is not None:
            return self._records.list_ids(self.resolve(query))
        raise ValidationError(f"Choose the records to {verb}: ids, or a query")

    # ------------------------------------------------------------------
    # Editing many records at once
    # ------------------------------------------------------------------

    def plan_bulk_edit(
        self,
        changes: dict[str, Any],
        *,
        ids: list[str] | None = None,
        query: RecordQuery | None = None,
        progress: Progress | None = None,
    ) -> RecordBulkEditPlanDTO:
        """What setting `changes` ({field name: value, None to clear}) on the
        chosen records (`ids`, or every record `query` lists) would do,
        without doing it: how many would change, how many already hold the
        values, which can't take them and why, and how many workflow runs it
        would start.

        Worked out over the set, not record by record: one statement reads,
        of every chosen record, only the values of the fields being changed
        (`RecordRepository.field_rows`), which says who already holds them;
        the checks a save runs are then run once for each different case (a
        kind of record, in a collection, changing these of the fields:
        `_checked_update` on one such record), since a value a field won't
        take is refused for every record of that kind alike. Only a change
        the database must be asked about per record (a link to another
        record, a field in a uniqueness key, a file) reads those records, as
        the edit does. `tests/services/test_record_bulk_edit.py` holds the
        plan to what the edit then does."""
        fields = list(changes)
        if not fields:
            raise ValidationError("Choose a field to set or clear")
        shapes = self._schema_svc.resolver()
        schemas = self._schema_svc.list_all()
        named = {
            str(f.id): f.name for s in schemas for f in s.fields if f.name in changes
        }
        if ids is not None:
            rows = self._records.field_rows(
                list(named), ids=self._chosen_ids(ids, None, "edit")
            )
        elif query is not None:
            rows = self._records.field_rows(list(named), query=self.resolve(query))
        else:
            raise ValidationError("Choose the records to edit: ids, or a query")
        if progress:
            progress.phase("Checking", len(rows))
        for dataset_id in {r[2] for r in rows if r[2] is not None}:
            self._permissions.require(permissions.WRITE_RECORDS, _as_uuid(dataset_id))
        paused = self._job_svc.is_paused() if self._job_svc else True
        counts = {"changing": 0, "unchanged": 0, "skipped": 0}
        skipped: list[tuple[Any, str]] = []
        runs = 0
        workflows: dict[str, int] = {}
        # What is the same for every record of a kind: whether it can take
        # these fields at all, the changes as it takes them, and whether its
        # checks need the database for each record.
        kinds: dict[
            Any, tuple[ResolvedSchema | None, str | None, dict[str, Any], bool]
        ] = {}
        # (kind, collection, the fields that change) -> why it is refused (or
        # None) and the workflows it starts, from one record checked in full.
        cases: dict[tuple[Any, ...], tuple[str | None, list[str]]] = {}
        slow: list[Any] = []

        def skip(record_id: Any, reason: str) -> None:
            counts["skipped"] += 1
            if len(skipped) < MAX_REPORTED:
                skipped.append((record_id, reason))

        for done, (record_id, schema_id, dataset_id, held) in enumerate(rows, 1):
            if schema_id not in kinds:
                shape = shapes(_as_uuid(schema_id))
                problem = _bulk_edit_problem(shape, fields)
                wanted = (
                    _strip_derived_file_keys(changes, shape.fields)
                    if shape is not None and problem is None
                    else {}
                )
                kinds[schema_id] = (
                    shape,
                    problem
                    or (None if shape is not None else "Its schema no longer exists"),
                    wanted,
                    shape is not None and self._edit_is_plain(shape, set(wanted)),
                )
            shape, problem, wanted, plain = kinds[schema_id]
            if problem or shape is None:
                skip(record_id, problem or "Its schema no longer exists")
                continue
            differing = frozenset(
                name
                for name, value in wanted.items()
                if held.get(str(shape.by_name[name].id)) != value
            )
            if not differing:
                counts["unchanged"] += 1
                continue
            if not plain:
                slow.append(record_id)
                continue
            case = (schema_id, dataset_id, differing)
            if case not in cases:
                cases[case] = self._edit_case(
                    _as_uuid(record_id), shape, wanted, shapes, paused
                )
            refused, starts = cases[case]
            if refused is not None:
                skip(record_id, refused)
                continue
            counts["changing"] += 1
            for name in starts:
                runs += 1
                workflows[name] = workflows.get(name, 0) + 1
            if progress and done % 5000 == 0:
                progress.advance(done)
        skips = self._named_skips(skipped, shapes)
        if slow:
            # These need the database for each record: read them, as the edit
            # does, remembering the keys the ones before would take.
            part = self._plan_one_by_one(
                changes, [_as_uuid(r) for r in slow], shapes, paused
            )
            counts["changing"] += part.changing
            counts["unchanged"] += part.unchanged
            counts["skipped"] += part.skipped
            skips = [*skips, *part.skipped_records][:MAX_REPORTED]
            runs += part.runs
            for name in part.workflows:
                workflows.setdefault(name, 0)
        if progress:
            progress.advance(len(rows))
        return RecordBulkEditPlanDTO(
            fields=fields,
            records=len(rows),
            changing=counts["changing"],
            unchanged=counts["unchanged"],
            skipped=counts["skipped"],
            skipped_records=skips,
            runs=runs,
            workflows=sorted(workflows),
            automation_paused=paused and self._job_svc is not None,
        )

    @staticmethod
    def _edit_is_plain(shape: ResolvedSchema, names: set[str]) -> bool:
        """Whether changing these fields of a record of this kind asks the
        database nothing about that record in particular: none is a file or a
        link to another record (catalogs and reachability), and none is part
        of a uniqueness key (which other record holds the value)."""
        ids = set()
        for name in names:
            found = shape.by_name.get(name)
            if found is None or found.dtype in _CATALOGUED_DTYPES:
                return False
            ids.add(str(found.id))
        return not any(ids & {str(i) for i in key} for key in shape.schema.unique_keys)

    def _edit_case(
        self,
        record_id: uuid.UUID,
        shape: ResolvedSchema,
        wanted: dict[str, Any],
        shapes: SchemaResolver,
        paused: bool,
    ) -> tuple[str | None, list[str]]:
        """One record of a case checked in full, as its save would be: why it
        is refused (None when it isn't) and the workflows it would start."""
        raw = self._records.get_by_id(record_id)
        if raw is None:
            return "It no longer exists", []
        merged = _patched(self._ids_to_names(raw.data, shape), wanted)
        if merged is None:
            return None, []
        dataset = (
            self._datasets.get_by_id(
                raw.dataset_id, include_deleted=True, with_count=False
            )
            if raw.dataset_id
            else None
        )
        try:
            before, id_data = self._checked_update(raw, merged, shape, dataset)
        except ValidationError as e:
            return str(e), []
        if paused or self._job_svc is None:
            return None, []
        after = self._ids_to_names(id_data, shape)
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        return None, [
            wf.name
            for wf in self._job_svc.triggered_by(
                shape.schema.name, "record_updated", changed
            )
        ]

    def _named_skips(
        self, skipped: list[tuple[Any, str]], shapes: SchemaResolver
    ) -> list[BulkEditSkipDTO]:
        """The records a plan names as left alone, with their names: only
        these few are read."""
        if not skipped:
            return []
        ids = [_as_uuid(record_id) for record_id, _ in skipped]
        found = {r.id: r for r in self._records.list_by_ids(ids)}
        return [
            BulkEditSkipDTO(
                record_id=rid,
                name=self._with_names(found[rid], shapes).natural_name
                if rid in found
                else None,
                reason=reason,
            )
            for rid, (_, reason) in zip(ids, skipped)
        ]

    def _plan_one_by_one(
        self,
        changes: dict[str, Any],
        chosen: list[uuid.UUID],
        shapes: SchemaResolver,
        paused: bool,
    ) -> RecordBulkEditPlanDTO:
        """The plan for records whose checks ask the database about each (a
        link, a uniqueness key, a file): read a page at a time and checked as
        the edit checks them, standing in for its earlier writes with the
        keys the records before would take (`_claim_keys`)."""
        fields = list(changes)
        datasets: dict[uuid.UUID, DatasetDTO | None] = {}
        claimed: dict[tuple[Any, ...], uuid.UUID] = {}
        workflows: dict[str, int] = {}
        skips: list[BulkEditSkipDTO] = []
        counts = {"records": 0, "changing": 0, "unchanged": 0, "skipped": 0}
        runs = 0
        for start in range(0, len(chosen), BULK_EDIT_PAGE):
            page = chosen[start : start + BULK_EDIT_PAGE]
            by_id = {r.id: r for r in self._records.list_by_ids(page)}
            for rid in page:
                raw = by_id.get(rid)
                if raw is None or raw.deleted_at is not None:
                    continue
                counts["records"] += 1
                shape = shapes(raw.schema_id)
                if shape is None:
                    continue
                wanted = _strip_derived_file_keys(changes, shape.fields)
                merged = _patched(self._ids_to_names(raw.data, shape), wanted)
                if merged is None:
                    counts["unchanged"] += 1
                    continue
                if raw.dataset_id not in datasets:
                    datasets[raw.dataset_id] = self._datasets.get_by_id(
                        raw.dataset_id, include_deleted=True, with_count=False
                    )
                dataset = datasets[raw.dataset_id]
                try:
                    before, id_data = self._checked_update(raw, merged, shape, dataset)
                    self._claim_keys(claimed, shape, raw, id_data)
                except ValidationError as e:
                    counts["skipped"] += 1
                    if len(skips) < MAX_REPORTED:
                        skips.append(
                            BulkEditSkipDTO(
                                record_id=raw.id,
                                name=self._with_names(raw, shapes).natural_name,
                                reason=str(e),
                            )
                        )
                    continue
                counts["changing"] += 1
                if not paused and self._job_svc is not None:
                    after = self._ids_to_names(id_data, shape)
                    changed = {
                        k
                        for k in set(before) | set(after)
                        if before.get(k) != after.get(k)
                    }
                    for wf in self._job_svc.triggered_by(
                        shape.schema.name, "record_updated", changed
                    ):
                        runs += 1
                        workflows[wf.name] = workflows.get(wf.name, 0) + 1
        return RecordBulkEditPlanDTO(
            fields=fields,
            records=counts["records"],
            changing=counts["changing"],
            unchanged=counts["unchanged"],
            skipped=counts["skipped"],
            skipped_records=skips,
            runs=runs,
            workflows=sorted(workflows),
            automation_paused=False,
        )

    def bulk_edit(
        self,
        changes: dict[str, Any],
        *,
        ids: list[str] | None = None,
        query: RecordQuery | None = None,
        progress: Progress | None = None,
    ) -> RecordBulkEditResultDTO:
        """Set (or, with None, clear) `changes` on every chosen record, in the
        caller's one transaction. Each record is saved as an edit of only
        those fields (`_patched`, the rule behind `patch`), through the
        checks, history and triggers of any save; one that already holds the
        values is not written. A record that can't take the change is left as
        it is and reported, the others go ahead: `plan_bulk_edit` says which
        beforehand. The lot is one event in Activity. `write_records` is
        asked for every collection involved before anything is written.

        A host that must not hold the database for the whole edit (the
        server, the CLI) runs `bulk_edit_chunks` instead and commits after
        each chunk."""
        result = RecordBulkEditResultDTO(0, 0, 0, [], 0)
        for result in self.bulk_edit_chunks(
            changes, ids=ids, query=query, progress=progress
        ):
            pass
        return result

    def bulk_edit_chunks(
        self,
        changes: dict[str, Any],
        *,
        ids: list[str] | None = None,
        query: RecordQuery | None = None,
        progress: Progress | None = None,
    ) -> Generator[RecordBulkEditResultDTO, None, None]:
        """`bulk_edit` a chunk of `BULK_EDIT_PAGE` records at a time: after
        each chunk it yields what has been done so far, and the caller
        commits (`AppContext.chunked_writes`), so the database's write lock
        is held for one chunk and other saves go in between two.

        A chunk is whole records only: each record's checks are done before
        anything of the chunk is written, then the chunk's records are saved
        in one statement (`update_many`) and its history entries in another,
        instead of a read, a write, two catalogs and an entry per record. A
        record whose change touches a file, a link to another record or a
        uniqueness key is saved by itself (`_write_update`), since those ask
        the database about that record.

        Every chunk's entries are in one batch (one event in Activity, undone
        whole by `revert_batch`, however many chunks went in); each record's
        entry is an action of its own, so one sent to a server between two
        chunks splits nothing. Nothing says where it got to: records that
        already hold the values are passed over, so an edit stopped half way
        (cancelled, a crash) is finished by running it again. Stop by closing
        the generator; what was committed stays."""
        fields = list(changes)
        if not fields:
            raise ValidationError("Choose a field to set or clear")
        chosen = self._chosen_ids(ids, query, "edit")
        for dataset_id in self._records.collections_of(chosen):
            self._permissions.require(permissions.WRITE_RECORDS, dataset_id)
        shapes = self._schema_svc.resolver()
        datasets: dict[uuid.UUID, DatasetDTO | None] = {}
        paused = self._job_svc.is_paused() if self._job_svc else True
        starts: dict[tuple[str, frozenset[str]], bool] = {}
        skips: list[BulkEditSkipDTO] = []
        counts = {"changing": 0, "unchanged": 0, "skipped": 0}
        runs = 0

        def skip(raw: RecordDTO, reason: str) -> None:
            counts["skipped"] += 1
            if len(skips) < MAX_REPORTED:
                skips.append(
                    BulkEditSkipDTO(
                        record_id=raw.id,
                        name=self._with_names(raw, shapes).natural_name,
                        reason=reason,
                    )
                )

        def so_far() -> RecordBulkEditResultDTO:
            return RecordBulkEditResultDTO(
                changed=counts["changing"],
                unchanged=counts["unchanged"],
                skipped=counts["skipped"],
                skipped_records=list(skips),
                runs=runs,
            )

        batch = (
            self._audit.batch("edit", ", ".join(fields))
            if self._audit is not None and len(chosen) > 1
            else nullcontext()
        )
        if progress:
            progress.phase("Changing records", len(chosen))
        with batch:
            for start in range(0, len(chosen), BULK_EDIT_PAGE):
                page = chosen[start : start + BULK_EDIT_PAGE]
                done = self._update_chunk(
                    {rid: changes for rid in page},
                    only_fields=fields,
                    shapes=shapes,
                    datasets=datasets,
                    starts=starts,
                    paused=paused,
                )
                counts["changing"] += done.changing
                counts["unchanged"] += done.unchanged
                runs += done.runs
                for rid, reason in done.failed.items():
                    skip(done.found[rid], reason)
                if progress:
                    progress.advance(min(start + BULK_EDIT_PAGE, len(chosen)))
                yield so_far()
        if not chosen:
            yield so_far()

    def remove_files(
        self,
        shas: set[str],
        record_ids: list[str],
        *,
        dry_run: bool = False,
    ) -> Generator[MissingFilesRemovalDTO, None, None]:
        """Take these files out of the records citing them: a file field that
        held one is cleared, a list loses the entries. Each record is saved as
        an ordinary edit of those fields (`patch`: checks, history, triggers,
        sync), the lot as one batch in Activity that `revert_batch` undoes whole.
        A record whose change would leave a required field empty is left as it
        is and named. `dry_run` only works out the same report. Chunks of
        `BULK_EDIT_PAGE` records; the caller commits after each yield, as for
        `bulk_edit_chunks`."""
        shapes = self._schema_svc.resolver()
        result = MissingFilesRemovalDTO()
        groups: dict[tuple[str | None, str, str], MissingFileGroupDTO] = {}
        group_files: dict[tuple[str | None, str, str], set[str]] = {}
        datasets: dict[uuid.UUID, DatasetDTO | None] = {}
        chosen = [uuid.UUID(r) for r in record_ids]
        batch = (
            self._audit.batch("edit", "remove missing files")
            if self._audit is not None and not dry_run and len(chosen) > 1
            else nullcontext()
        )
        with batch:
            for start in range(0, len(chosen), BULK_EDIT_PAGE):
                page = chosen[start : start + BULK_EDIT_PAGE]
                records_on_page = self._records.list_by_ids(page)
                self._require_each(permissions.DELETE_FILES, records_on_page)
                for raw in records_on_page:
                    if raw.deleted_at is not None:
                        continue
                    shape = shapes(raw.schema_id)
                    if shape is None:
                        continue
                    if raw.dataset_id not in datasets:
                        datasets[raw.dataset_id] = self._datasets.get_by_id(
                            raw.dataset_id, include_deleted=True, with_count=False
                        )
                    dataset = datasets[raw.dataset_id]
                    changes: dict[str, Any] = {}
                    cited: dict[str, set[str]] = {}
                    blocked: str | None = None
                    for name, value in self._ids_to_names(raw.data, shape).items():
                        gone = _cited_among(value, shas)
                        if not gone:
                            continue
                        left = (
                            None
                            if isinstance(value, dict)
                            else [v for v in value if not _cites(v, shas)]
                        )
                        spec = shape.by_name.get(name)
                        if spec is not None and spec.required and not left:
                            blocked = (
                                f"'{spec.label or name}' is required and would be "
                                "left empty"
                            )
                            break
                        changes[name] = (
                            left
                            if left is None
                            else [plain_data({"v": x})["v"] for x in left]
                        )
                        cited[name] = gone
                    if blocked:
                        result.skipped_count += 1
                        if len(result.skipped) < MAX_REPORTED:
                            result.skipped.append(
                                BulkEditSkipDTO(
                                    record_id=raw.id,
                                    name=self._with_names(raw, shapes).natural_name,
                                    reason=blocked,
                                )
                            )
                        continue
                    if not changes:
                        continue
                    if not dry_run:
                        try:
                            self.patch(str(raw.id), changes)
                        except ValidationError as e:
                            result.skipped_count += 1
                            if len(result.skipped) < MAX_REPORTED:
                                result.skipped.append(
                                    BulkEditSkipDTO(raw.id, None, str(e))
                                )
                            continue
                    result.changed += 1
                    for name, gone in cited.items():
                        key = (
                            dataset.name if dataset else None,
                            shape.schema.name,
                            name,
                        )
                        group = groups.setdefault(
                            key, MissingFileGroupDTO(key[0], key[1], key[2])
                        )
                        group.records += 1
                        group_files.setdefault(key, set()).update(gone)
                result.groups = sorted(
                    (
                        dataclasses.replace(g, files=len(group_files[k]))
                        for k, g in groups.items()
                    ),
                    key=lambda g: (-g.records, g.schema, g.field),
                )
                yield result

    def _save_checked(
        self,
        raw: RecordDTO,
        merged: dict[str, Any],
        names: set[str],
        shape: ResolvedSchema,
        shapes: SchemaResolver,
        dataset: DatasetDTO | None,
        together: list[tuple[RecordDTO, dict[str, Any], dict[str, Any]]],
    ) -> int:
        """Check `raw` saved as `merged` (its whole data, by name, with only
        `names` changed). A plain change is added to `together`, for
        `_write_together` to save with the rest of its chunk; any other is
        saved now, since it asks the database about this record. How many
        workflow runs were queued by a save made now. Raises
        `ValidationError`, writing nothing."""
        if self._edit_is_plain(shape, names):
            before, id_data = self._checked_update(raw, merged, shape, dataset)
            if self._stays_plain(shape, raw.data, id_data):
                together.append((raw, id_data, before))
                return 0
        return self._write_update(raw, merged, shapes, dataset)[1]

    def _update_chunk(
        self,
        patches: dict[uuid.UUID, dict[str, Any]],
        *,
        only_fields: list[str] | None = None,
        unset: bool = False,
        shapes: SchemaResolver | None = None,
        datasets: dict[uuid.UUID, DatasetDTO | None] | None = None,
        starts: dict[tuple[str, frozenset[str]], bool] | None = None,
        paused: bool | None = None,
    ) -> _UpdateChunk:
        """Set these fields (by name; None clears one) on each of these records:
        the one chunk of field changes, whatever asked for it (a bulk edit, the
        undo of one, the core's `apply_changes`). Every record is checked first
        (a record that can't take it is left whole and named, one that already
        holds the values is passed over), then the records are saved in one
        statement and their history entries in another, with a workflow run only
        for a change that starts one (`_write_together`); a record whose change
        touches a file, a link or a unique key is saved by itself
        (`_save_checked`), since those ask the database about that record.
        `only_fields` makes a record refuse a field it can't hold itself (a bulk
        edit chooses the fields for every record); with `unset` a None removes
        the field (as it was before it was set) instead of storing a null. Needs `write_records` in
        every collection it touches."""
        shapes = shapes or self._schema_svc.resolver()
        if paused is None:
            paused = self._job_svc.is_paused() if self._job_svc else True
        datasets = {} if datasets is None else datasets
        starts = {} if starts is None else starts
        out = _UpdateChunk()
        together: list[tuple[RecordDTO, dict[str, Any], dict[str, Any]]] = []
        out.found = {
            r.id: r
            for r in self._records.list_by_ids(list(patches))
            if r.deleted_at is None
        }
        out.gone = set(patches) - set(out.found)
        for dataset_id in {r.dataset_id for r in out.found.values()}:
            self._permissions.require(permissions.WRITE_RECORDS, dataset_id)
        for rid in patches:
            raw = out.found.get(rid)
            if raw is None:
                continue
            shape = shapes(raw.schema_id)
            problem = _bulk_edit_problem(shape, only_fields) if only_fields else None
            if problem or shape is None:
                out.failed[rid] = problem or "Its schema no longer exists"
                continue
            wanted = _strip_derived_file_keys(patches[rid], shape.fields)
            merged = _patched(self._ids_to_names(raw.data, shape), wanted)
            if merged is None:
                out.unchanged += 1
                continue
            if unset:
                merged = {
                    k: v for k, v in merged.items() if v is not None or k not in wanted
                }
            if raw.dataset_id not in datasets:
                datasets[raw.dataset_id] = self._datasets.get_by_id(
                    raw.dataset_id, include_deleted=True, with_count=False
                )
            try:
                out.runs += self._save_checked(
                    raw,
                    merged,
                    set(wanted),
                    shape,
                    shapes,
                    datasets[raw.dataset_id],
                    together,
                )
            except ValidationError as e:
                out.failed[rid] = str(e)
                continue
            out.changing += 1
        out.runs += self._write_together(together, shapes, paused, starts)
        return out

    @staticmethod
    def _stays_plain(
        shape: ResolvedSchema, stored: dict[str, Any], to_store: dict[str, Any]
    ) -> bool:
        """Whether everything that differs between a record's data and what a
        checked save would store is a plain value (a default the save filled
        in could be a link or part of a key)."""
        keyed = {str(i) for key in shape.schema.unique_keys for i in key}
        for field_id in set(stored) | set(to_store):
            if stored.get(field_id) == to_store.get(field_id):
                continue
            name = shape.id_to_name.get(field_id)
            found = shape.by_name.get(name) if name else None
            if found is None or found.dtype in _CATALOGUED_DTYPES or field_id in keyed:
                return False
        return True

    def _write_together(
        self,
        checked: list[tuple[RecordDTO, dict[str, Any], dict[str, Any]]],
        shapes: SchemaResolver,
        paused: bool,
        starts: dict[tuple[str, frozenset[str]], bool],
    ) -> int:
        """Save a chunk's checked records at once: one statement for the
        records, one for their history entries (an entry each, as a save
        writes), and a workflow run only for a record whose change starts
        one. How many runs were queued. `starts` remembers, for a kind and
        the fields that changed, whether any workflow watches them."""
        if not checked:
            return 0
        stamp = _dt.now(timezone.utc)
        # The entries are made ready first (nothing is sent until the records
        # are saved), so the database is written to, and so locked, only for
        # the two statements and the commit that follows.
        every = [
            (raw, dataclasses.replace(raw, data=data, updated_at=stamp), before)
            for raw, data, before in checked
        ]
        if self._audit:
            self._audit.log_changes(
                "update",
                "record",
                (
                    (raw.id, self._snapshot(raw), self._snapshot(saved))
                    for raw, saved, _ in every
                ),
            )
        self._records.update_many([(raw.id, data) for raw, data, _ in checked], stamp)
        runs = 0
        for raw, saved, before in every:
            id_data = saved.data
            if paused or self._job_svc is None:
                continue
            shape = shapes(raw.schema_id)
            if shape is None:
                continue
            after = self._ids_to_names(id_data, shape)
            changed = frozenset(
                k for k in set(before) | set(after) if before.get(k) != after.get(k)
            )
            watched = (shape.schema.name, changed)
            if watched not in starts:
                starts[watched] = bool(
                    self._job_svc.triggered_by(
                        shape.schema.name, "record_updated", set(changed)
                    )
                )
            if starts[watched]:
                runs += len(
                    self._job_svc.trigger_for_record(
                        self._with_names(saved, shapes),
                        "record_updated",
                        changed_fields=set(changed),
                        depth=0,
                        changes={k: (before.get(k), after.get(k)) for k in changed},
                        cause=None,
                    )
                )
        return runs

    def _claim_keys(
        self,
        claimed: dict[tuple[Any, ...], uuid.UUID],
        shape: ResolvedSchema,
        raw: RecordDTO,
        id_data: dict[str, Any],
    ) -> None:
        """For a plan: refuse a record whose new values would share a unique
        key with an earlier record of the same plan (`_check_unique` only sees
        what is stored, and the earlier one isn't yet), else remember its keys.
        A key whose values the record already held is not taken anew."""
        for key in shape.schema.unique_keys:
            values = key_values(id_data, key)
            if values is None or key_values(raw.data, key) == values:
                continue
            slot = (raw.dataset_id, shape.schema.id, raw.parent_record_id, tuple(key))
            spot = (*slot, *values)
            if spot in claimed and claimed[spot] != raw.id:
                names = [shape.id_to_name.get(i, i) for i in key]
                raise DuplicateRecordError(
                    f"Another of the chosen records would get the same "
                    f"{_join_names(names)}. {_join_names(names, cap=True)} must be "
                    + (
                        "unique within its parent."
                        if raw.parent_record_id
                        else "unique within the collection."
                    ),
                    existing_id=str(claimed[spot]),
                    fields=names,
                )
            claimed[spot] = raw.id

    def _move_kind_problems(
        self, roots: list[RecordDTO], above: RecordDTO | None
    ) -> list[str]:
        """Each root must be able to sit where it would go: inside `above`
        only if its kind nests in that record's kind, at the top only if its
        kind is a top-level one."""
        problems: list[str] = []
        for schema_id in dict.fromkeys(r.schema_id for r in roots):
            schema = self._schema_svc.get_by_id(schema_id, include_deleted=True)
            if schema is None:
                continue
            holder = (
                self._schema_svc.get_by_id(schema.parent_id, include_deleted=True)
                if schema.parent_id
                else None
            )
            if above is None and holder is not None:
                problems.append(
                    f"A {schema.display_name} sits inside a {holder.display_name}: "
                    f"choose the {holder.display_name} it goes in."
                )
            elif above is not None and schema.parent_id != above.schema_id:
                problems.append(
                    f"A {schema.display_name} can't go inside "
                    f"'{self._deleted_name(above)}' ({above.schema_name}): "
                    + (
                        f"it sits inside a {holder.display_name}."
                        if holder is not None
                        else "it sits at the top of a collection."
                    )
                )
        return problems

    def _move_reference_problems(
        self, records: list[RecordDTO], moving: set[uuid.UUID], target: DatasetDTO
    ) -> list[str]:
        """A reference reaches a record in the same collection or in a global
        one. Moving must not break one: from a moved record to one staying
        behind in a local collection, or from a record staying behind to one
        moved into a local collection."""
        problems: list[str] = []
        live = [r.id for r in records if r.deleted_at is None]
        target_global = target.scope == GLOBAL
        collections: dict[uuid.UUID, DatasetDTO | None] = {}

        def collection(dataset_id: uuid.UUID) -> DatasetDTO | None:
            if dataset_id not in collections:
                collections[dataset_id] = self._datasets.get_by_id(
                    dataset_id, with_count=False
                )
            return collections[dataset_id]

        outgoing = {
            rid: tid
            for rid, _, tid in self._records.references_of(live)
            if tid not in moving
        }
        targets = {
            r.id: r for r in self._records.list_by_ids(list(set(outgoing.values())))
        }
        broken_out: dict[str, set[uuid.UUID]] = {}
        for rid, tid in outgoing.items():
            other = targets.get(tid)
            if other is None or other.dataset_id == target.id:
                continue
            holder = collection(other.dataset_id)
            if holder is not None and holder.scope != GLOBAL:
                broken_out.setdefault(holder.name, set()).add(rid)
        for name, referrers in sorted(broken_out.items()):
            problems.append(
                f"{_count(len(referrers), 'record')} being moved "
                f"reference{'s' if len(referrers) == 1 else ''} records that would "
                f"stay behind in '{name}', which only its own records can "
                f"reference. Move those too, or make '{name}' global."
            )
        if not target_global:
            field_ids = [uuid.UUID(f) for f in self._reference_field_map()]
            referrers = {
                rid
                for rid, _, _ in self._records.referrers_of(live, field_ids)
                if rid not in moving
            }
            broken_in: dict[str, set[uuid.UUID]] = {}
            for other in self._records.list_by_ids(list(referrers)):
                if other.dataset_id == target.id:
                    continue
                holder = collection(other.dataset_id)
                if holder is not None:
                    broken_in.setdefault(holder.name, set()).add(other.id)
            for name, found in sorted(broken_in.items()):
                problems.append(
                    f"{_count(len(found), 'record')} in '{name}' "
                    f"reference{'s' if len(found) == 1 else ''} records being moved "
                    f"and could no longer reach them in '{target.name}'. Move "
                    f"those too, or make '{target.name}' global."
                )
        return problems

    def _move_unique_problems(
        self, roots: list[RecordDTO], target: DatasetDTO, parent_id: uuid.UUID | None
    ) -> list[str]:
        """A root lands in a new place (collection and parent): nothing there
        may share a uniqueness key with it, and no two roots may share one."""
        problems: list[str] = []
        shapes = self._schema_svc.resolver()
        seen: dict[tuple[uuid.UUID, tuple[str, ...], tuple[Any, ...]], RecordDTO] = {}
        for root in roots:
            shape = shapes(root.schema_id)
            if shape is None or not shape.schema.unique_keys:
                continue
            try:
                self._check_unique(
                    shape, target.id, parent_id, root.data, exclude_id=root.id
                )
            except DuplicateRecordError as e:
                problems.append(str(e))
            for key in shape.schema.unique_keys:
                values = key_values(root.data, key)
                if values is None:
                    continue
                mark = (root.schema_id, tuple(key), tuple(values))
                other = seen.setdefault(mark, root)
                if other is not root:
                    names = [shape.id_to_name.get(i, i) for i in key]
                    problems.append(
                        f"Two of the chosen {shape.schema.display_name} records "
                        f"share the same {_join_names(names)} "
                        f"('{self._deleted_name(other)}' and "
                        f"'{self._deleted_name(root)}'): they can't both be "
                        "in one place."
                    )
        return problems

    def placed_with_parent(
        self, state: dict[str, Any], cache: IncomingCache | None = None
    ) -> dict[str, Any]:
        """The record state with its collection made its parent's, when the
        parent is held here in another one: a child's collection *is* its
        parent's, so a change made against a parent that has since moved
        follows the parent rather than being refused (the state the authority
        settles on then differs from what was sent, and is sent back)."""
        parent_id = state.get("parent_record_id")
        if not parent_id:
            return state
        try:
            parent = self._record_at(
                uuid.UUID(str(parent_id)), cache, include_deleted=True
            )
        except ValueError:
            return state
        if parent is None or str(parent.dataset_id) == str(state.get("dataset_id")):
            return state
        return {**state, "dataset_id": str(parent.dataset_id)}

    def placement_mismatches(self, record_ids: list[uuid.UUID]) -> int:
        """How many of these records, or of the records directly beneath them,
        are in another collection than the record above them: what the
        database refuses when a transaction commits, asked beforehand."""
        return self._records.dataset_mismatches(record_ids)

    def subtree_ids(self, record_id: str) -> list[uuid.UUID]:
        """A record and every record beneath it, live or deleted."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        levels = self._records.subtree_levels([record.id], deleted=None)
        return [rid for level in levels for rid in level]

    def restore_group_ids(self, record_id: str) -> list[uuid.UUID]:
        """The records that come back when this deleted one is restored: it, and
        what was deleted with it."""
        return self._restore_group(self._deleted_record(record_id))

    def restore_plan(self, record_id: str) -> RestorePlanDTO:
        """What restoring this deleted record would do, without doing it: what
        comes back with it, and what, if anything, is in the way. A record
        can't come back while its collection, its schema or a record above it
        is still deleted -- it would be live but nowhere to be seen."""
        record = self._deleted_record(record_id)
        dataset = self._datasets.get_by_id(
            record.dataset_id,
            include_deleted=True,
            with_count=False,
        )
        group = self._restore_group(record)
        blocker = self._restore_blocker(record, dataset)
        return RestorePlanDTO(
            kind="record",
            id=record.id,
            name=self._deleted_name(record),
            records=len(group),
            blocked_by=blocker,
            # Only worth saying once nothing else stands in the way.
            conflict=None if blocker else self._restore_conflict(group),
            collection=dataset.name if dataset else None,
            collection_id=dataset.id if dataset else None,
            deleted_at=record.deleted_at,
            parents_needed=(
                len(self._deleted_above(record))
                if blocker is not None and blocker.kind == "record"
                else None
            ),
        )

    def _deleted_above(self, record: RecordDTO) -> list[RecordDTO]:
        """The deleted records directly above this one, topmost first: what has
        to come back for it to be seen."""
        above: list[RecordDTO] = []
        current = record
        while current.parent_record_id is not None:
            parent = self._records.get_by_prefix(
                str(current.parent_record_id), include_deleted=True
            )
            if parent is None or parent.deleted_at is None:
                break
            above.append(parent)
            current = parent
        return list(reversed(above))

    def deleted_above(self, record_id: str) -> list[RecordDTO]:
        """For a live record, the deleted records directly above it, topmost
        first and named; empty when what it sits under is live (or the record
        is itself deleted). Such a record is out of sight -- nothing above it
        lists it -- and an authority refuses it. It comes about from history
        (a record brought back by itself before that was refused, a cascade
        applied before cascades synced), never from an edit today."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        if record.deleted_at is not None:
            return []
        return [self._with_names(r) for r in self._deleted_above(record)]

    def restore_above(self, record_id: str) -> list[RecordDTO]:
        """Bring back what a live record sits under that is deleted: each
        deleted record directly above it, by itself, so their other children
        stay deleted. Checked, in the history and synced like any restore.
        Refused while what the topmost sits in (its collection, its schema) is
        deleted, and when one would clash with a live record's unique key. The
        one way an out-of-sight record is put back in place: the record page,
        the project check and a refused change's review all use it."""
        above = self.deleted_above(record_id)
        if not above:
            raise ValidationError("Nothing it sits under is deleted.")
        plan = self.restore_plan(str(above[0].id))
        if plan.blocked_by is not None and plan.blocked_by.kind != "record":
            raise ValidationError(plan.blocked_message or "It can't come back yet.")
        every = [a.id for a in above]
        conflict = self._restore_conflict(every)
        if conflict:
            raise DuplicateRecordError(
                conflict.message,
                conflict.existing_id,
                conflict.fields,
                conflict.existing_name,
            )
        self._restore_ids(every)
        return [self.get(str(i)) for i in every]

    def orphans(self, limit: int = 200) -> tuple[list[OrphanDTO], int]:
        """Every live record that sits under a deleted one (see
        `deleted_above`), each with what it sits under, at most `limit`; and how
        many there are."""
        found, total = self._records.live_under_deleted(limit)
        out = [
            OrphanDTO(
                self._with_names(r),
                [self._with_names(a) for a in self._deleted_above(r)],
            )
            for r in found
        ]
        return out, total

    def _deleted_record(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        if record.deleted_at is None:
            raise ValidationError(f"Record '{record_id}' is not deleted")
        return record

    def _deleted_name(self, record: RecordDTO) -> str:
        named = self.labels([str(record.id)])
        return (named[0].natural_name if named else None) or (
            f"{record.schema_name} {str(record.id)[:8]}"
        )

    def _restore_group(self, record: RecordDTO) -> list[uuid.UUID]:
        """The record and what was deleted *with* it: the descendants stamped
        with the same moment, reached through others in the group. A child
        deleted on its own earlier stays deleted, as does everything under it."""
        levels = self._records.subtree_levels([record.id], deleted=True)
        every = [rid for level in levels for rid in level]
        rows = {r.id: r for r in self._records.list_by_ids(every)}
        group = [record.id]
        kept = {record.id}
        for rid in every:
            row = rows[rid]
            if (
                rid != record.id
                and row.deleted_at == record.deleted_at
                and row.parent_record_id in kept
            ):
                group.append(rid)
                kept.add(rid)
        return group

    def _restore_clashes(
        self, rows: list[RecordDTO]
    ) -> dict[uuid.UUID, DuplicateRecordError]:
        """Which of these deleted records can't come back because their
        schema's unique key is held by another live record, or by an earlier one
        in this same set (two deleted records can have shared values with
        nothing live between them). By record id, with `rows`' order deciding
        which of two such records is the one that comes back.

        Which hold a live record's values is asked a chunk of places at a time
        (`key_clashes`); the error of a clashing record is then made the way a
        save makes it."""
        clashes: dict[uuid.UUID, DuplicateRecordError] = {}
        shapes = self._schema_svc.resolver()
        live = self._live_key_clashes(rows, shapes)
        taken: dict[tuple, RecordDTO] = {}
        for row in rows:
            shape = shapes(row.schema_id)
            if shape is None or not shape.schema.unique_keys:
                continue
            if row.id in live:
                try:
                    self._check_unique(
                        shape,
                        row.dataset_id,
                        row.parent_record_id,
                        row.data,
                        exclude_id=row.id,
                    )
                except DuplicateRecordError as e:
                    clashes[row.id] = e
                    continue
            for key in shape.schema.unique_keys:
                values = key_values(row.data, key)
                if values is None:
                    continue
                marker = (
                    row.dataset_id,
                    row.schema_id,
                    row.parent_record_id,
                    tuple(key),
                    tuple(_hashable(v) for v in values),
                )
                other = taken.get(marker)
                if other is not None:
                    names = [shape.id_to_name.get(i, i) for i in key]
                    clashes[row.id] = DuplicateRecordError(
                        f"'{self._deleted_name(row)}' and "
                        f"'{self._deleted_name(other)}' have the same "
                        f"{_join_names(names)}",
                        existing_id=str(other.id),
                        fields=names,
                        existing_name=self._deleted_name(other),
                    )
                    break
                taken[marker] = row
        return clashes

    def _live_key_clashes(
        self, rows: list[RecordDTO], shapes: SchemaResolver
    ) -> set[uuid.UUID]:
        """The records among `rows` whose values for some unique key a live
        record of their schema already holds, in the same place."""
        places: dict[
            tuple[uuid.UUID, uuid.UUID],
            list[tuple[uuid.UUID, uuid.UUID | None, dict[str, Any]]],
        ] = {}
        for row in rows:
            shape = shapes(row.schema_id)
            if shape is None:
                continue
            for key in shape.schema.unique_keys:
                values = key_values(row.data, key)
                if values is not None:
                    places.setdefault((row.dataset_id, row.schema_id), []).append(
                        (row.id, row.parent_record_id, dict(zip(key, values)))
                    )
        found: set[uuid.UUID] = set()
        for (dataset_id, schema_id), held in places.items():
            hit = self._records.key_clashes(
                dataset_id, schema_id, [(parent, key) for _, parent, key in held]
            )
            found.update(held[i][0] for i in hit)
        return found

    def _restore_conflict(self, group: list[uuid.UUID]) -> RestoreConflictDTO | None:
        """The first record in `group` that can't come back for a clash of
        unique values (see `_restore_clashes`)."""
        rows = self._records.list_by_ids(group)
        clashes = self._restore_clashes(rows)
        for row in rows:
            e = clashes.get(row.id)
            if e is not None:
                return RestoreConflictDTO(
                    record_id=row.id,
                    record_name=self._deleted_name(row),
                    existing_id=e.existing_id or "",
                    existing_name=e.existing_name or "",
                    fields=e.fields,
                )
        return None

    def _restore_blocker(
        self, record: RecordDTO, dataset: DatasetDTO | None
    ) -> BlockerDTO | None:
        if dataset is not None and dataset.deleted_at is not None:
            return BlockerDTO("collection", dataset.id, dataset.name)
        schema = self._schema_svc._repo.get_by_id(
            record.schema_id, include_deleted=True
        )
        if schema is not None and schema.deleted_at is not None:
            return BlockerDTO("schema", schema.id, schema.name)
        # The topmost of the deleted records directly above this one: bringing
        # that back brings its group back, and the next step is then open.
        top: RecordDTO | None = None
        current = record
        while current.parent_record_id is not None:
            parent = self._records.get_by_prefix(
                str(current.parent_record_id), include_deleted=True
            )
            if parent is None or parent.deleted_at is None:
                break
            top = current = parent
        if top is not None:
            return BlockerDTO("record", top.id, self._deleted_name(top))
        return None

    def plan_restore_set(
        self,
        ids: list[str],
        covered_collections: frozenset[str] | set[str] = frozenset(),
        covered_schemas: frozenset[str] | set[str] = frozenset(),
        exact: bool = False,
    ) -> RestoreSetDTO:
        """Which of these deleted records can come back, and what comes back
        with them, for all of them at once and however many there are: only the
        few columns the decision needs are read (a statement per chunk of ids
        and per level of the tree, never one per record), and the answer is
        worked out in memory, parents first, in one pass. Nothing is dropped for
        size; what is left out is what is genuinely held back.

        A record is held back while its collection or schema is deleted, or the
        record above it is deleted and is not itself coming back (one in the
        set, or one deleted with a record that is). `covered_*` name the
        collections and schemas a caller is restoring first, so records under
        them count as coming. What was deleted with a record (the records under
        it stamped the same) comes with it; a group that holds a record that
        can't come back, for a clash of unique values, stays whole, deleted.
        With `exact` nothing comes with a record: just these."""
        wanted: list[uuid.UUID] = []
        for raw in ids:
            try:
                wanted.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        wanted = list(dict.fromkeys(wanted))
        found = self._records.restore_rows(wanted, deleted_only=True)
        plan = RestoreSetDTO()
        if len(found) < len(wanted):
            there = {r.id for r in found}
            plan.absent = [i for i in wanted if i not in there]
        if not found:
            return plan
        rows = {r.id: r for r in found}
        chosen = list(rows)
        # The records above, a level at a time (live or deleted).
        frontier = {
            r.parent_record_id
            for r in found
            if r.parent_record_id is not None and r.parent_record_id not in rows
        }
        while frontier:
            above = self._records.restore_rows(list(frontier))
            rows.update({r.id: r for r in above})
            frontier = {
                r.parent_record_id
                for r in above
                if r.parent_record_id is not None and r.parent_record_id not in rows
            }
        # What was deleted with each: the records under it stamped alike,
        # reached through others stamped alike.
        children: dict[uuid.UUID, list[uuid.UUID]] = {}
        level = [] if exact else list(chosen)
        seen = set(chosen)
        if level:
            # Usually a bulk delete is chosen whole, and what was deleted with
            # each is chosen too: a count says so without reading it again.
            inside = [
                (r.parent_record_id, r.id)
                for r in found
                if r.parent_record_id in seen
                and rows[r.parent_record_id].deleted_at == r.deleted_at
            ]
            if self._records.count_deleted_with(level) == len(inside):
                for parent_id, child_id in inside:
                    children.setdefault(parent_id, []).append(child_id)
                level = []
        while level:
            below = self._records.deleted_with(level)
            for child_id, parent_id in below:
                children.setdefault(parent_id, []).append(child_id)
            level = list(dict.fromkeys(c for c, _ in below if c not in seen))
            seen.update(level)
            fresh = [c for c in level if c not in rows]
            rows.update({r.id: r for r in self._records.restore_rows(fresh)})
        # A clash of unique values holds back every group it is in (a group
        # half restored would be worse): note which records sit above one.
        tainted = self._restore_taint(rows, seen)
        held = self._held_by_schema_or_collection(
            [rows[i] for i in chosen], covered_collections, covered_schemas
        )
        coming: dict[uuid.UUID, None] = {}
        for rid in _parents_first_ids(chosen, rows):
            row = rows[rid]
            if rid in coming:
                plan.restored += 1  # comes back with a record above it
                continue
            above_row = rows.get(row.parent_record_id) if row.parent_record_id else None
            if (
                rid in tainted
                or rid in held
                or (
                    above_row is not None
                    and above_row.deleted_at is not None
                    and above_row.id not in coming
                )
            ):
                plan.blocked.append(rid)
                continue
            plan.restored += 1
            queue = [rid]
            for member in queue:  # parents before what is under them
                if member not in coming:
                    coming[member] = None
                    queue.extend(children.get(member, ()))
        plan.coming = list(coming)
        plan.rows = {rid: rows[rid] for rid in coming}
        return plan

    def _held_by_schema_or_collection(
        self,
        records: list[RestoreRow],
        covered_collections: frozenset[str] | set[str],
        covered_schemas: frozenset[str] | set[str],
    ) -> set[uuid.UUID]:
        """Which of these records sit in a deleted collection or schema that is
        not one being restored. Each collection and schema is looked up once."""
        gone_datasets: set[uuid.UUID] = set()
        for did in {r.dataset_id for r in records}:
            d = self._datasets.get_by_id(did, include_deleted=True, with_count=False)
            if d is not None and d.deleted_at is not None:
                if d.name not in covered_collections:
                    gone_datasets.add(did)
        gone_schemas: set[uuid.UUID] = set()
        for sid in {r.schema_id for r in records}:
            sc = self._schema_svc._repo.get_by_id(sid, include_deleted=True)
            if sc is not None and sc.deleted_at is not None:
                if sc.name not in covered_schemas:
                    gone_schemas.add(sid)
        return {
            r.id
            for r in records
            if r.dataset_id in gone_datasets or r.schema_id in gone_schemas
        }

    def _restore_taint(
        self, rows: dict[uuid.UUID, RestoreRow], candidates: set[uuid.UUID]
    ) -> set[uuid.UUID]:
        """The records that can't come back because one that would come with
        them (itself, or one deleted with it) clashes on a unique key (see
        `_restore_clashes`). Only the records of schemas with a unique key are
        read in full."""
        shapes = self._schema_svc.resolver()
        keyed: dict[uuid.UUID, bool] = {}
        for sid in {rows[i].schema_id for i in candidates}:
            shape = shapes(sid)
            keyed[sid] = bool(shape is not None and shape.schema.unique_keys)
        if not any(keyed.values()):
            return set()
        ordered = _parents_first_ids(list(candidates), rows)
        ids = [i for i in ordered if keyed[rows[i].schema_id]]
        by_id = {r.id: r for r in self._records.list_by_ids(ids)}
        clashes = self._restore_clashes([by_id[i] for i in ids if i in by_id])
        tainted: set[uuid.UUID] = set()
        for rid in clashes:
            current = rid
            while current not in tainted:
                tainted.add(current)
                row = rows[current]
                above = rows.get(row.parent_record_id) if row.parent_record_id else None
                if above is None or above.deleted_at != row.deleted_at:
                    break
                current = above.id
        return tainted

    def restore_set(
        self, ids: Iterable[str | uuid.UUID], *, dry_run: bool = False
    ) -> RestoreSetResultDTO:
        """Restore every one of these deleted records that nothing deleted holds
        back, each with what was deleted with it, as one action in history:
        the update and the history entries are written a chunk at a time, so it
        is a few dozen statements however many records there are. Those held
        back are returned in `left`."""
        plan = self.plan_restore_set([str(i) for i in ids])
        if plan.coming and dry_run:
            self._require_restore(plan.coming, plan.rows)
        elif plan.coming:
            self._restore_write(plan.coming, plan.rows)
        return RestoreSetResultDTO(
            restored=plan.restored,
            came_back=len(plan.coming),
            left=[str(i) for i in plan.blocked],
            absent=[str(i) for i in plan.absent],
        )

    def _restore_write(
        self,
        ids: list[uuid.UUID],
        rows: dict[uuid.UUID, RestoreRow],
    ) -> None:
        """Bring back these deleted records, `ids` parents before what sits
        under them (a child can't come back under a parent still deleted, here
        or wherever the entries are applied next), `rows` saying what each was:
        the permission to write in every collection first, one update per chunk
        and the history entries a chunk at a time, no values read. The lot is
        one batch, an action per tree (a record and what comes back with it
        go together or not at all; a tree refused when sent splits nothing
        else). The one place a record is brought back."""
        self._require_restore(ids, rows)
        self._records.restore_many(ids)
        if not self._audit:
            return
        ops = _tree_ops({i: rows[i].parent_record_id for i in ids})
        with _audit_batch(self._audit, "restore", len(ids) > 1):
            self._audit.log_changes(
                "restore",
                "record",
                (
                    (i, _place(rows[i], rows[i].deleted_at), _place(rows[i], None))
                    for i in ids
                ),
                ops=ops,
            )

    def _require_restore(
        self, ids: list[uuid.UUID], rows: dict[uuid.UUID, RestoreRow]
    ) -> None:
        """The permission to write in every collection these records are in."""
        self._require_each(
            permissions.WRITE_RECORDS,
            {rows[i].dataset_id: rows[i] for i in ids}.values(),
        )

    def require_write(self, ids: Iterable[uuid.UUID]) -> None:
        """`write_records` in every collection these records are in (what a
        preview of a change asks, as the change itself will)."""
        for dataset_id in self._records.collections_of(list(ids)):
            self._permissions.require(permissions.WRITE_RECORDS, dataset_id)

    def _restore_ids(self, ids: list[uuid.UUID]) -> None:
        """`_restore_write` for records already known to be able to come back:
        their columns are read and put parents first."""
        rows = {r.id: r for r in self._records.restore_rows(ids)}
        ordered = _parents_first_ids([i for i in dict.fromkeys(ids) if i in rows], rows)
        self._restore_write(ordered, rows)

    def restore_records(
        self, ids: list[str], with_parents: bool = True
    ) -> RestoreSetResultDTO:
        """Restore exactly these deleted records and nothing else: not what was
        deleted alongside them, which is how a bulk delete of sixty records can
        be undone for three of them. A record under a deleted record comes back
        only with it, so with `with_parents` (the default) the deleted records
        above a chosen one come back too, each by itself; without it such a
        record is left. One held back by a deleted collection or schema is left
        either way. Planned and written by the same code as every restore."""
        wanted: list[uuid.UUID] = []
        for raw in ids:
            try:
                wanted.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        chosen = {
            r.id
            for r in self._records.restore_rows(
                list(dict.fromkeys(wanted)), deleted_only=True
            )
        }
        everything = set(chosen)
        if with_parents:
            frontier = set(chosen)
            while frontier:
                above = {
                    r.parent_record_id
                    for r in self._records.restore_rows(list(frontier))
                    if r.parent_record_id is not None
                }
                frontier = {
                    r.id
                    for r in self._records.restore_rows(list(above), deleted_only=True)
                    if r.id not in everything
                }
                everything |= frontier
        plan = self.plan_restore_set([str(i) for i in everything], exact=True)
        if plan.coming:
            self._restore_write(plan.coming, plan.rows)
        return RestoreSetResultDTO(
            restored=len([i for i in plan.coming if i in chosen]),
            came_back=len(plan.coming),
            left=[str(i) for i in plan.blocked if i in chosen],
        )

    def _restore_blockers(
        self, records: list[RecordDTO]
    ) -> dict[uuid.UUID, BlockerDTO | None]:
        """`_restore_blocker` for many records at once. Collections and schemas
        are looked up once each, and the records above them a level at a time.
        A record blocker carries no name (it takes a rendering per record);
        callers that need one use `restore_plan`."""
        datasets = {
            did: self._datasets.get_by_id(did, include_deleted=True, with_count=False)
            for did in {r.dataset_id for r in records}
        }
        schemas = {
            sid: self._schema_svc._repo.get_by_id(sid, include_deleted=True)
            for sid in {r.schema_id for r in records}
        }
        known = {r.id: r for r in records}
        frontier = {
            r.parent_record_id
            for r in records
            if r.parent_record_id is not None and r.parent_record_id not in known
        }
        while frontier:
            found = self._records.list_by_ids(list(frontier))
            known.update({r.id: r for r in found})
            frontier = {
                r.parent_record_id
                for r in found
                if r.parent_record_id is not None and r.parent_record_id not in known
            }
        blockers: dict[uuid.UUID, BlockerDTO | None] = {}
        for record in records:
            dataset = datasets[record.dataset_id]
            schema = schemas[record.schema_id]
            if dataset is not None and dataset.deleted_at is not None:
                blockers[record.id] = BlockerDTO("collection", dataset.id, dataset.name)
            elif schema is not None and schema.deleted_at is not None:
                blockers[record.id] = BlockerDTO("schema", schema.id, schema.name)
            else:
                top: RecordDTO | None = None
                current = record
                while current.parent_record_id is not None:
                    parent = known.get(current.parent_record_id)
                    if parent is None or parent.deleted_at is None:
                        break
                    top = current = parent
                blockers[record.id] = (
                    BlockerDTO("record", top.id, "") if top is not None else None
                )
        return blockers

    def restore(
        self,
        record_id: str,
        only_this: bool = False,
        with_parents: bool = False,
    ) -> RecordDTO:
        """Undo delete(): the record and what was deleted with it become live
        again. Refused while its collection, schema or a parent record is still
        deleted (see `restore_plan`).

        Two choices, because a delete is not all-or-nothing:
        `only_this` brings back just this record, not what was deleted
        alongside it (its children); `with_parents` lets a record held back only
        by deleted records above it come back anyway, bringing those back too,
        each by itself, so its siblings stay deleted. Restoring one selection of
        a deleted recording then doesn't bring back all of them."""
        record = self._deleted_record(record_id)
        self._permissions.require(permissions.WRITE_RECORDS, record.dataset_id)
        plan = self.restore_plan(str(record.id))
        needs_parents = plan.blocked_by is not None and plan.blocked_by.kind == "record"
        if plan.held_back_message and not (with_parents and needs_parents):
            raise ValidationError(plan.held_back_message)
        every = [record.id] if only_this else self._restore_group(record)
        if with_parents and needs_parents:
            every = [a.id for a in self._deleted_above(record)] + every
        # Checked against what actually comes back, so restoring just this
        # record sidesteps a clash that only a child has.
        conflict = self._restore_conflict(every)
        if conflict:
            raise DuplicateRecordError(
                conflict.message,
                conflict.existing_id,
                conflict.fields,
                conflict.existing_name,
            )
        self._restore_ids(every)
        return self.get(str(record.id))

    @property
    def records_repo(self) -> RecordRepository:
        """The repository records are stored in, for the services whose actions
        change records as a side effect (a collection's delete takes its
        records) and say so in history (`services/cascades`)."""
        return self._records

    def purgeable_deleted(
        self, cutoff: _dt
    ) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
        """(id, collection id, schema id) of the records deleted before `cutoff`
        that can go for good without leaving a child pointing at them."""
        return self._records.purgeable_deleted(cutoff)

    def purge_records(self, ids: list[uuid.UUID]) -> None:
        """Permanently remove these already-deleted records. Every history entry
        about them is deleted, and each leaves one tombstone: that it was
        permanently deleted, which record, and when, never what it held. The
        caller has checked they are safe to remove (see `purgeable_deleted`)."""
        with _audit_batch(self._audit, "purge", len(ids) > 1):
            for start in range(0, len(ids), 500):
                self._purge_chunk(ids[start : start + 500])

    def _purge_chunk(self, ids: list[uuid.UUID]) -> None:
        going = self._records.list_by_ids(ids)
        self._require_each(permissions.DELETE, going)
        if self._audit:
            stones = [(gone.id, tombstone(self._snapshot(gone))) for gone in going]
            self._audit.forget_records(ids)
            for record_id, stone in stones:
                self._audit.log_change("purge", "record", record_id, stone, None)
        self._records.purge_many(ids)

    def purge(self, record_id: str) -> None:
        """Permanently remove a record (and its cascade-deleted descendants)
        that's already in Recently Deleted — a separate, explicit action
        from delete(). Irreversible, and so is the history: every entry about
        the records removed is deleted, leaving one tombstone for each."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        if record.deleted_at is None:
            raise ValidationError(
                f"Record '{record_id}' must be deleted before it can be purged"
            )
        self.purge_records(self.purge_set(record_id))

    def purge_set(self, record_id: str) -> list[uuid.UUID]:
        """The records a permanent delete of this deleted record removes: it and
        everything beneath it."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        levels = self._records.subtree_levels([record.id], deleted=None)
        return [rid for level in levels for rid in level]

    def _reference_field_map(
        self, target_schema: str | None = None
    ) -> dict[str, tuple[str, str]]:
        """field id (str) -> (field name, dtype) for every reference/reference_list
        field across all schemas -- record data is stored id-keyed (see
        _names_to_ids), and a reference field on any schema can point at a
        record of any other schema, so this has to span all of them.

        With `target_schema`, fields restricted to a different target schema
        are left out (an unrestricted field can point anywhere)."""
        result: dict[str, tuple[str, str]] = {}
        for schema in self._schema_svc.list_all():
            for f in schema.fields:
                if f.dtype in ("reference", "reference_list"):
                    restricted_to = (f.restrictions or {}).get("schema")
                    if target_schema and restricted_to not in (None, target_schema):
                        continue
                    result[str(f.id)] = (f.name, f.dtype)
        return result

    def _find_referrers(
        self,
        target_ids: set[uuid.UUID],
        exclude_ids: set[uuid.UUID],
        target_schema: str | None = None,
    ) -> list[tuple[RecordDTO, dict[str, str]]]:
        """Records outside exclude_ids holding a reference/reference_list value
        that points at any of target_ids. Returns (referrer, {field_id: field_name})
        pairs so callers know exactly which field(s) to null out or report.

        `target_schema` (the targets' schema name) skips fields whose `schema`
        restriction names a different schema -- they can't hold these targets."""
        field_map = self._reference_field_map(target_schema)
        if not field_map:
            return []
        matched: dict[uuid.UUID, dict[str, str]] = {}
        for referrer_id, field_id, _ in self._records.referrers_of(
            list(target_ids), [uuid.UUID(f) for f in field_map]
        ):
            if referrer_id not in exclude_ids:
                matched.setdefault(referrer_id, {})[str(field_id)] = field_map[
                    str(field_id)
                ][0]
        records = {r.id: r for r in self._records.list_by_ids(list(matched))}
        return [(records[rid], m) for rid, m in matched.items() if rid in records]

    def _handle_referrers(
        self, target_ids: set[uuid.UUID], force: bool, dry_run: bool = False
    ) -> None:
        """Block a delete of target_ids if anything outside the batch still
        references it, unless force=True -- in which case the referencing
        fields are cleared (ON DELETE SET NULL) and audit-logged instead."""
        field_map = self._reference_field_map()
        if field_map and self._records.hidden_referrers(
            list(target_ids), [uuid.UUID(f) for f in field_map]
        ):
            # Something the caller cannot see still points at it, and a
            # delete (forced or not) must neither leave that dangling nor
            # reach into what is hidden: refused, without saying what.
            raise ValidationError(
                "Cannot delete: still referenced by records you cannot see."
            )
        referrers = self._find_referrers(target_ids, exclude_ids=target_ids)
        if not referrers:
            return
        if not force:
            raise ValidationError(_referrers_message(referrers))
        if dry_run:
            return

        target_strs = {str(t) for t in target_ids}
        for rec, matched_fields in referrers:
            new_data = dict(rec.data)
            for fid_str in matched_fields:
                val = new_data.get(fid_str)
                if isinstance(val, list):
                    new_data[fid_str] = [v for v in val if v not in target_strs]
                else:
                    new_data[fid_str] = None
            updated = self._records.update(id=rec.id, data=new_data)
            if self._audit:
                self._audit.log_change(
                    "update",
                    "record",
                    rec.id,
                    self._snapshot(rec),
                    self._snapshot(updated),
                )

    def find_dangling_references(self) -> list[dict[str, Any]]:
        """Every reference/reference_list value pointing at a record that no
        longer exists. Surfaces integrity violations left over from before
        delete-time enforcement existed (CIVEX-169) -- used by `civex doctor`."""
        field_map = self._reference_field_map()
        return [
            {
                "record_id": record_id,
                "schema_name": schema_name,
                "field_name": field_map[str(field_id)][0],
                "dangling_target_id": target_id,
            }
            for record_id, schema_name, field_id, target_id in (
                self._records.dangling_references([uuid.UUID(f) for f in field_map])
            )
        ]


def _tree_actions(records: list[RecordDTO]) -> dict[uuid.UUID, uuid.UUID]:
    """An action id per tree among `records`: each record gets the id of the
    topmost of them it sits under (or its own), so a tree is one action."""
    parent_of = {r.id: r.parent_record_id for r in records}
    ops: dict[uuid.UUID, uuid.UUID] = {}
    out: dict[uuid.UUID, uuid.UUID] = {}
    for record in records:
        root = record.id
        while parent_of.get(root) in parent_of:
            root = parent_of[root]  # type: ignore[assignment]
        out[record.id] = ops.setdefault(root, uuid.uuid4())
    return out


@dataclasses.dataclass
class _UpdateChunk:
    """What `RecordService._update_chunk` did with a chunk of field changes."""

    changing: int = 0  # records changed
    unchanged: int = 0  # records that already held the values
    runs: int = 0  # workflow runs queued
    found: dict[uuid.UUID, RecordDTO] = dataclasses.field(
        default_factory=dict
    )  # the live ones
    gone: set[uuid.UUID] = dataclasses.field(default_factory=set)  # missing or deleted
    failed: dict[uuid.UUID, str] = dataclasses.field(
        default_factory=dict
    )  # left, and why


def _tree_ops(
    parent_of: dict[uuid.UUID, uuid.UUID | None],
) -> dict[uuid.UUID, uuid.UUID]:
    """An action id per tree among these records: each gets the id of the
    topmost of them it sits under (or its own), so a tree is one action."""
    ops: dict[uuid.UUID, uuid.UUID] = {}
    out: dict[uuid.UUID, uuid.UUID] = {}
    for rid in parent_of:
        root = rid
        while parent_of.get(root) in parent_of:
            root = parent_of[root]  # type: ignore[assignment]
        out[rid] = ops.setdefault(root, uuid.uuid4())
    return out


def _place(row: RestoreRow, deleted_at: _dt | None) -> dict[str, Any]:
    """A record as a restore's history entry holds it: where it sits and whether
    it is deleted, which is all a restore changes (no values are read)."""
    return {
        "id": str(row.id),
        "dataset_id": str(row.dataset_id),
        "schema_id": str(row.schema_id),
        "parent_record_id": str(row.parent_record_id) if row.parent_record_id else None,
        "deleted_at": deleted_at.isoformat() if deleted_at else None,
    }


def _parents_first_ids(
    ids: list[uuid.UUID], rows: dict[uuid.UUID, RestoreRow]
) -> list[uuid.UUID]:
    """`ids` shallowest first, by how many records above each is known: a
    record comes after every record above it that is among them. Ties keep
    their order."""
    depth: dict[uuid.UUID, int] = {}

    def of(rid: uuid.UUID) -> int:
        trail: list[uuid.UUID] = []
        current: uuid.UUID | None = rid
        while current is not None and current not in depth:
            trail.append(current)
            row = rows.get(current)
            current = row.parent_record_id if row is not None else None
        base = depth[current] + 1 if current is not None else 0
        for i, step in enumerate(reversed(trail)):
            depth[step] = base + i
        return depth[rid]

    return sorted(ids, key=of)


def _stamp_of(text: Any) -> _dt:
    """When a record was deleted, as its state says (any moment, if it does
    not parse: only that it is deleted is asked of it)."""
    try:
        at = _dt.fromisoformat(str(text))
    except ValueError:
        return _dt.min.replace(tzinfo=timezone.utc)
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)
