from __future__ import annotations

import dataclasses
from contextlib import nullcontext
import re
import uuid
from datetime import date as _date, datetime as _dt, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from civex.domain.file_refs import without_file_locations
from civex.domain.dtos import (
    OrphanDTO,
    DERIVED_FILE_KEYS,
    BlockerDTO,
    DatasetDTO,
    FieldDTO,
    FieldValueDTO,
    FileRef,
    RecordDTO,
    ReferrerGroupDTO,
    ResolvedField,
    ResolvedSchema,
    RestoreConflictDTO,
    RestorePlanDTO,
    RestoreSetDTO,
    RestoreSetResultDTO,
    SchemaDTO,
)
from civex.domain import geo as geo_domain
from civex.domain.audit_diff import tombstone
from civex.domain import partial_dates, templating, units
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
from civex.domain.query import RecordQuery, ResolvedQuery
from civex.domain.scopes import GLOBAL, can_reference
from civex.domain.timezones import parse_datetime
from civex.domain.uniqueness import key_values
from civex.repositories.protocols import (
    AuditRepository,
    DatasetRepository,
    FileObjectStore,
    RecordRepository,
)
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

    if not restrictions:
        return

    if dtype in ("integer", "float"):
        if isinstance(value, str) or isinstance(value, bool):
            raise ValidationError(f"Field '{field_name}': '{value}' is not a number")
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
        refs = value if isinstance(value, list) else [value]
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
            if not isinstance(ref, dict):
                continue
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


def _audit_batch(audit: AuditRepository | None, kind: str, many: bool):
    """One batch for an operation that touches several records, so history
    shows it as one event. A single record is just its own entry."""
    return audit.batch(kind) if audit is not None and many else nullcontext()


def _is_blank_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _file_dicts(value: Any) -> list[dict[str, Any]]:
    """The file reference dicts in a `file` or `file_list` value."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _strip_derived_file_keys(
    data: dict[str, Any], fields: list[ResolvedField]
) -> dict[str, Any]:
    """`data` without the response-only keys on its file values."""

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: v for k, v in item.items() if k not in DERIVED_FILE_KEYS}
        return item

    result = dict(data)
    for rf in fields:
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


class RecordService:
    def __init__(
        self,
        schema_svc: SchemaService,
        dataset_repo: DatasetRepository,
        record_repo: RecordRepository,
        file_store: FileObjectStore,
        job_svc: WorkflowJobService | None = None,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self._schema_svc = schema_svc
        self._datasets = dataset_repo
        self._records = record_repo
        self._files = file_store
        # This project follows an authority, so a file its records cite that no
        # drive here holds can be fetched from it (set by `build_local_context`).
        self.files_from_server: Callable[[], bool] = lambda: False
        self._job_svc = job_svc
        self._audit = audit_repo

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
        # A deleted field's value stays in the stored data (so a restore brings it
        # back) but isn't a field the record has now.
        return {
            shape.id_to_name.get(k, k): v
            for k, v in data.items()
            if k not in shape.deleted_by_id
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
        return self._attach_file_locations(
            self._label_references(
                self._name_files_from_relatives(records, shapes), shapes
            ),
            shapes,
        )

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
        volume_of = self._files.locate_volumes(unpointed) if unpointed else {}
        from_server = None in volume_of.values() and self.files_from_server()
        status = {
            name: self._files.volume_status(name)
            for name in {v for v in volume_of.values() if v} | set(used.values())
        }

        def location(record_id: uuid.UUID, sha: str | None) -> dict[str, Any]:
            volume = used.get((record_id, sha or "")) or volume_of.get(sha or "")
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
                }
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
            }

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
                    with_schemas=False,
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

    def _check_schema_allowed(self, dataset: DatasetDTO, schema: SchemaDTO) -> None:
        """A collection only holds records of the schemas it is for."""
        if schema.name not in dataset.schemas:
            raise ValidationError(
                f"Schema '{schema.name}' is not enabled for collection "
                f"'{dataset.name}' -- add it to the collection's schemas first"
            )

    def _check_unique(
        self,
        shape: ResolvedSchema | None,
        dataset_id: uuid.UUID,
        parent_record_id: uuid.UUID | None,
        id_data: dict[str, Any],
        exclude_id: uuid.UUID | None = None,
        unchanged: dict[str, Any] | None = None,
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
    ) -> None:
        """Every reference/reference_list value must point at a live record in
        this collection or in a global one (see civex.domain.scopes). Values
        equal to the record's stored ones (`unchanged`) are not re-checked, so
        editing a record never fails over a reference it already held."""
        if shape is None:
            return
        wanted: list[tuple[str, Any]] = []
        for rf in shape.fields:
            field = rf.field
            if field.dtype not in ("reference", "reference_list"):
                continue
            value = data.get(field.name)
            if value is None or (
                unchanged is not None and unchanged.get(field.name) == value
            ):
                continue
            for item in value if isinstance(value, list) else [value]:
                wanted.append((field.name, item))
        self._check_reference_targets(wanted, dataset)

    def _check_reference_targets(
        self, wanted: list[tuple[str, Any]], dataset: DatasetDTO
    ) -> None:
        """Check every (field name, record id) in `wanted` against `dataset`:
        the target must be a live record here or in a global collection. All
        the targets are fetched together, and each collection looked up once,
        however many references a record holds."""
        if not wanted:
            return
        ids: list[uuid.UUID] = []
        for field_name, raw in wanted:
            try:
                ids.append(uuid.UUID(str(raw)))
            except ValueError:
                raise ValidationError(
                    f"Field '{field_name}': '{raw}' is not a record id"
                ) from None
        targets = {t.id: t for t in self._records.list_by_ids(ids)}
        owners: dict[uuid.UUID, DatasetDTO | None] = {}
        for (field_name, raw), target_id in zip(wanted, ids):
            target = targets.get(target_id)
            if target is None or target.deleted_at is not None:
                raise ValidationError(f"Field '{field_name}': record {raw} not found")
            if target.dataset_id == dataset.id:
                continue
            if target.dataset_id not in owners:
                owners[target.dataset_id] = self._datasets.get_by_id(
                    target.dataset_id,
                    include_deleted=True,
                    with_count=False,
                    with_schemas=False,
                )
            owner = owners[target.dataset_id]
            if owner is None or not can_reference(dataset.id, owner.id, owner.scope):
                where = f"collection '{owner.name}'" if owner else "another collection"
                raise ValidationError(
                    f"Field '{field_name}': record {str(target_id)[:8]} is in "
                    f"{where}, which is local. A record can only reference "
                    f"records in its own collection or in a global collection."
                )

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
                    with_schemas=False,
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

    def patched_data(
        self, record_id: str, fields: dict[str, Any]
    ) -> tuple[RecordDTO, dict[str, Any] | None]:
        """The record as it is *now*, and the whole data it would hold with only
        `fields` changed (None when they already hold those values, so there is
        nothing to write). `update` replaces a record's whole data, so a caller
        that knows only some fields must start from the current ones: this is
        the one place that does, for `patch` and for a plugin's `patch_record`."""
        current = self.get(record_id)
        existing = without_file_locations(current.data)
        if all(existing.get(k) == v for k, v in fields.items()):
            return current, None
        return current, {**existing, **fields}

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

    def check_incoming(
        self, state: dict[str, Any], head: dict[str, Any] | None
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
        shape = self._schema_svc.resolver()(schema_id)
        if shape is None:
            raise ValidationError("The record's schema does not exist here")
        dataset = self._datasets.get_by_id(
            dataset_id, include_deleted=True, with_count=False
        )
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
            above = self._records.get_by_id(parent_id, include_deleted=True)
            if above is not None and above.deleted_at is not None:
                raise ValidationError(
                    "The record it sits under was deleted on the server"
                )

        if head is None or head.get("deleted_at"):
            # Made, or brought back: only where it could be added.
            self._check_schema_allowed(dataset, shape.schema)
            if shape.schema.parent_id:
                parent = self._records.get_by_id(parent_id) if parent_id else None
                if parent is None:
                    raise ValidationError(
                        f"Schema '{shape.schema.name}' inherits from another "
                        "schema: its parent record does not exist here"
                    )
                self._check_parent(parent, dataset, shape.schema)
        # A record that is deleted here and comes back is checked in full: its
        # stored values say nothing about whether they still fit.
        before = head.get("data") or {} if head and not head.get("deleted_at") else None
        named = self._ids_to_names(data, shape)
        before_named = self._ids_to_names(before, shape) if before is not None else None
        changed = {
            k: v
            for k, v in named.items()
            if before_named is None or before_named.get(k) != v
        }
        self._validate_data(changed, shape)
        self._check_references(named, shape, dataset, unchanged=before_named)
        self._check_unique(
            shape, dataset.id, parent_id, data, exclude_id=record_id, unchanged=before
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
    ) -> RecordDTO:
        """Create a record. `with_labels=False` skips resolving its reference
        values' display names and collection for the returned DTO (a few
        queries) -- for loops, like a restore, that discard the result."""
        dataset = self._datasets.get_by_name(dataset_name, with_count=False)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")

        schema = self._schema_svc.get(schema_name)
        self._check_schema_allowed(dataset, schema)

        # Apply field defaults before validation
        shape = self._schema_svc.resolve(schema)
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
            parent_record = self._records.get_by_prefix(parent_record_id)
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
        self._check_references(data, shape, dataset)
        id_data = self._names_to_ids(data, shape)
        self._check_unique(shape, dataset.id, resolved_parent_id, id_data)
        dto = self._records.create(
            dataset_id=dataset.id,
            schema_id=schema.id,
            data=id_data,
            parent_record_id=resolved_parent_id,
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

    def get(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id)
        if not record:
            raise NotFoundError(f"Record '{record_id}' not found")
        return self._attach_reference_labels([self._with_names(record)])[0]

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
        # Apply field defaults before validation
        shapes = self._schema_svc.resolver()
        shape = shapes(raw.schema_id)
        data = self._apply_defaults(data, shape)
        old_data = self._ids_to_names(raw.data, shape)
        dataset = (
            self._datasets.get_by_id(
                raw.dataset_id,
                include_deleted=True,
                with_count=False,
                with_schemas=False,
            )
            if raw.dataset_id
            else None
        )
        if shape is not None:
            data = _strip_derived_file_keys(data, shape.fields)
        data = self._normalise_datetimes(
            data,
            shape,
            dataset.timezone if dataset else None,
            unchanged=old_data,
        )
        self._validate_data(data, shape)
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
            self._job_svc.trigger_for_record(
                named,
                "record_updated",
                changed_fields=changed,
                depth=_job_depth,
                changes={k: (old_data.get(k), new_data.get(k)) for k in changed},
                cause=_cause,
            )
        return self._attach_reference_labels([named], shapes)[0]

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
            dataset = self._datasets.get_by_name(
                query.dataset, with_count=False, with_schemas=False
            )
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

        within = None
        if query.within:
            if schema is None:
                raise ValidationError("'within' needs a schema to list")
            ancestor = self._records.get_by_prefix(query.within)
            if not ancestor:
                raise NotFoundError(f"Record '{query.within}' not found")
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
            field_filters=field_filters,
            search=query.search or None,
            filter_tree=self._resolve_filter(schema, query.filter_tree),
            sort=self._resolve_sort(schema, query.sort),
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
        record, not the child's own data)."""
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
        if schema is None:
            # No schema to resolve names against (a mixed-schema list):
            # conditions pass through by stored key, as they always have.
            if any(leaf.schema for leaf in leaves(node)):
                raise ValidationError(
                    "A filter condition naming a schema needs a schema to query"
                )
            return node
        related = self._relations(schema)

        def resolve_leaf(leaf: FilterCondition) -> FilterCondition:
            f, rel = self._locate(schema, related, leaf.field, leaf.schema, "filter")
            return dataclasses.replace(leaf, field=str(f.id), rel=rel)

        return map_leaves(node, resolve_leaf)

    def _resolve_sort(
        self, schema: SchemaDTO | None, sort: list[dict[str, Any]] | None
    ) -> list[SortKey] | None:
        if not sort:
            return None
        if schema is None:
            raise ValidationError("Sorting needs a schema to list")
        related = self._relations(schema)
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

    def query_records(
        self,
        query: RecordQuery,
        limit: int = 50,
        offset: int = 0,
        columns: list[str] | None = None,
        child_counts: bool = False,
        after: tuple[_dt, uuid.UUID] | None = None,
    ) -> list[RecordDTO]:
        """One page of `query`. `columns` asks for values that aren't in a
        record's own data (an inherited field, a `ref.field` join), attached
        as `derived`; `child_counts` attaches per-child-schema counts. `after`
        continues an unsorted listing past a record (see `stream_records`)."""
        records = self._records.list_filtered(
            self.resolve(query), offset, limit, after=after
        )
        named = self._attach_reference_labels(self._with_names_many(records))
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

    def stream_records(
        self,
        query: RecordQuery,
        page_size: int = 500,
        columns: list[str] | None = None,
    ) -> Iterator[list[RecordDTO]]:
        """Every matching record, one page at a time -- for exports, which
        must not hold the whole result set in memory.

        An unsorted walk continues from the last record's (created_at, id)
        rather than an ever-growing OFFSET, which would re-read every row it
        skips and make a large export quadratic. A custom sort has no such
        cursor, so it still pages by offset."""
        offset = 0
        after: tuple[_dt, uuid.UUID] | None = None
        while True:
            page = self.query_records(
                query,
                limit=page_size,
                offset=0 if after else offset,
                columns=columns,
                after=after,
            )
            if not page:
                return
            yield page
            if len(page) < page_size:
                return
            if query.sort:
                offset += page_size
            else:
                after = (page[-1].created_at, page[-1].id)

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
                n = self.count_records(
                    dataclasses.replace(query, schema=descendant.name)
                )
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
    ) -> list[RecordDTO]:
        return self.query_records(
            RecordQuery(
                dataset=dataset_name,
                schema=schema_name,
                parent_record_id=parent_record_id,
                where=filters or [],
                filter_tree=filter_tree,
                search=search,
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
    ) -> int:
        return self.count_records(
            RecordQuery(
                dataset=dataset_name,
                schema=schema_name,
                parent_record_id=parent_record_id,
                where=filters or [],
                filter_tree=filter_tree,
                search=search,
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
    ) -> Iterator[list[RecordDTO]]:
        return self.stream_records(
            RecordQuery(
                dataset=dataset_name,
                schema=schema_name,
                parent_record_id=parent_record_id,
                where=filters or [],
                filter_tree=filter_tree,
                search=search,
            ),
            page_size=page_size,
        )

    def count_by_schema_search(
        self, schema_name: str, search: str | None = None
    ) -> int:
        """Total matching `find_by_schema` -- same predicate, in SQL."""
        schema = self._schema_svc.get(schema_name)
        return self._records.count_schema_matches(schema.id, search=search)

    def find_by_schema(
        self,
        schema_name: str,
        search: str | None = None,
        limit: int = 20,
        reachable_from: str | None = None,
    ) -> list[RecordDTO]:
        """`reachable_from` (a collection name) limits the search to records a
        record in that collection may reference: its own collection's plus
        those of global collections (civex.domain.scopes). What a reference
        picker searches, so it never offers another local collection's
        records."""
        schema = self._schema_svc.get(schema_name)
        dataset_ids = None
        if reachable_from:
            source = self._datasets.get_by_name(
                reachable_from, with_count=False, with_schemas=False
            )
            if not source:
                raise NotFoundError(f"Dataset '{reachable_from}' not found")
            dataset_ids = [source.id] + [
                d.id
                for d in self._datasets.list_all(with_count=False)
                if d.scope == GLOBAL and d.id != source.id
            ]
        records = self._records.list_by_schema(
            schema.id, search=search, limit=limit, dataset_ids=dataset_ids
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
        query = query.strip()
        if not query:
            return []
        dataset_id = None
        if collection:
            dataset = self._datasets.get_by_name(
                collection, with_count=False, with_schemas=False
            )
            if not dataset:
                raise NotFoundError(f"Dataset '{collection}' not found")
            dataset_id = dataset.id
        records = self._records.search_all(query, limit=limit, dataset_id=dataset_id)
        return self._attach_reference_labels(self._with_names_many(records))

    # ------------------------------------------------------------------
    # Columns that aren't in a record's own data
    # ------------------------------------------------------------------

    def validate_columns(self, schema: SchemaDTO, columns: list[str]) -> None:
        """Every column must be a field of `schema` (own or inherited) or a
        single-hop `ref_field.target_field` join through a reference field."""
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schema_svc.collect_fields(schema)
        }
        unknown = []
        for col in columns:
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
        values = self._derived_values(schema_name, records, columns)
        if not any(values):
            return records
        return [
            dataclasses.replace(record, derived=derived)
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

        def plain(name: str) -> tuple[str, int] | None:
            """(field id, hops up) for a non-dotted column, None if unknown."""
            try:
                f, rel = self._locate(schema, related, name, None, "column")
            except ValidationError:
                return None
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
                plans[col] = ("inherited", located)
        if not plans:
            return [{} for _ in records]

        chains = self._ancestor_chains(records, max(p[1][1] for p in plans.values()))
        id_to_name = self._schema_svc.id_to_name_map(schema)

        def value(record: RecordDTO, located: tuple[str, int]) -> Any:
            field_id, hops = located
            if hops == 0:
                return record.data.get(id_to_name[field_id])
            ancestor = chains[record.id][hops - 1]
            return ancestor.data.get(field_id) if ancestor else None

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
            derived: dict[str, Any] = {}
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
            found.extend(self._attach_reference_labels(named, shapes))
            if on_level:
                on_level(len(found))
        return found

    def get_many(self, record_ids: list[str]) -> list[RecordDTO]:
        """These live records in the order asked, in the full response form
        (names, reference labels, where each file is stored), in a fixed number
        of queries. Ids that aren't live records are left out."""
        ids: list[uuid.UUID] = []
        for raw in dict.fromkeys(record_ids):
            try:
                ids.append(uuid.UUID(raw))
            except (ValueError, AttributeError, TypeError):
                continue
        found = {r.id: r for r in self._records.list_by_ids(ids) if not r.deleted_at}
        shapes = self._schema_svc.resolver()
        named = [self._with_names(found[i], shapes) for i in ids if i in found]
        return self._attach_reference_labels(named, shapes)

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
        self._delete_records([record.id], force)

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
        return self._delete_records(live, force)

    def delete_matching(self, query: RecordQuery, force: bool = False) -> int:
        """Delete every record `query` matches -- what "select all N
        matching" means, as opposed to deleting the ids on one page."""
        return self._delete_records(self._records.list_ids(self.resolve(query)), force)

    def delete_all(
        self, dataset_name: str, schema_name: str | None = None, force: bool = False
    ) -> int:
        return self.delete_matching(
            RecordQuery(dataset=dataset_name, schema=schema_name), force
        )

    def _delete_records(self, ids: list[uuid.UUID], force: bool) -> int:
        """Delete `ids` and everything beneath them. Returns how many of `ids`
        were deleted in their own right -- one already beneath another is
        deleted with it, and not counted again.

        The whole subtree is found a level at a time and soft-deleted with a
        bulk UPDATE, not a query and a flush per record."""
        levels = self._records.subtree_levels(ids, deleted=False)
        if not levels:
            return 0
        every = [rid for level in levels for rid in level]
        doomed = set(every)
        self._handle_referrers(doomed, force)
        records = self._records.list_by_ids(every)
        # One instant: it is the entries' time and what the records are stamped
        # with, so every device that applies these entries stamps them alike.
        stamp = _dt.now(timezone.utc)
        if self._audit:
            # Each tree is one action: a record and everything beneath it go
            # together or not at all (a child left live under a deleted parent
            # is not a project), but separate trees deleted at once don't.
            tree = _tree_actions(records)
            with _audit_batch(self._audit, "delete", len(records) > 1):
                for record in records:
                    self._audit.log_change(
                        "delete",
                        "record",
                        record.id,
                        self._snapshot(record),
                        None,
                        timestamp=stamp,
                        op=tree[record.id],
                    )
        self._records.delete_many(every, stamp)
        requested = set(ids)
        return sum(
            1
            for record in records
            if record.id in requested and record.parent_record_id not in doomed
        )

    def list_deleted(
        self,
        dataset_name: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[RecordDTO]:
        dataset_id = None
        if dataset_name:
            dataset = self._datasets.get_by_name(
                dataset_name, with_count=False, with_schemas=False
            )
            if not dataset:
                raise NotFoundError(f"Dataset '{dataset_name}' not found")
            dataset_id = dataset.id
        return self._attach_reference_labels(
            self._with_names_many(
                self._records.list_deleted(dataset_id, offset=offset, limit=limit)
            )
        )

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
            with_schemas=False,
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
        before = {r.id: self._snapshot(r) for r in self._records.list_by_ids(every)}
        self._records.restore_many(every)
        self._log_restored(every, before)
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
        which of two such records is the one that comes back."""
        clashes: dict[uuid.UUID, DuplicateRecordError] = {}
        shapes = self._schema_svc.resolver()
        taken: dict[tuple, RecordDTO] = {}
        for row in rows:
            shape = shapes(row.schema_id)
            if shape is None or not shape.schema.unique_keys:
                continue
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
    ) -> RestoreSetDTO:
        """Which of these deleted records can come back, for all of them at once:
        the records, their collections, schemas and ancestors, and what each
        brings back with it, are looked up together rather than record by record
        (`restore_plan` per record is a dozen queries each, so a bulk delete of a
        few hundred took minutes to even describe).

        A record is held back while its collection, its schema, or the topmost
        deleted record above it is deleted -- unless that is itself being
        restored (`covered_*` name the collections and schemas that are, and any
        chosen record is): it then comes back with it."""
        wanted: list[uuid.UUID] = []
        for raw in ids:
            try:
                wanted.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        rows = [
            r
            for r in self._records.list_by_ids(list(dict.fromkeys(wanted)))
            if r.deleted_at is not None
        ]
        chosen = {r.id for r in rows}
        blockers = self._restore_blockers(rows)
        groups = self._restore_groups(rows)
        plan = RestoreSetDTO(groups=groups)
        # A record whose group holds one that can't come back for a clash of
        # unique values is left whole (a half-restored group would be worse).
        clashing: set[uuid.UUID] = set()
        members = {
            r.id: r
            for r in self._records.list_by_ids(
                list(dict.fromkeys(m for g in groups.values() for m in g))
            )
        }
        clashes = self._restore_clashes(list(members.values()))
        for root, group in groups.items():
            if any(m in clashes for m in group):
                clashing.add(root)
        for record in rows:
            if record.id in clashing:
                plan.blocked.append(record.id)
                continue
            blocker = blockers[record.id]
            covered = blocker is not None and (
                (blocker.kind == "record" and blocker.id in chosen)
                or (
                    blocker.kind == "collection" and blocker.name in covered_collections
                )
                or (blocker.kind == "schema" and blocker.name in covered_schemas)
            )
            if blocker is not None and not covered:
                plan.blocked.append(record.id)
                continue
            plan.coming.update(groups[record.id])
            if blocker is None:
                plan.ready.append(record.id)
            else:
                plan.waiting.append(record.id)
        return plan

    def restore_set(self, ids: list[str]) -> RestoreSetResultDTO:
        """Restore every one of these deleted records that nothing deleted holds
        back, each with what was deleted with it, in one go: one lookup, one
        update and one history entry per record, not a full plan and restore
        per record. Those held back are returned in `left` (restoring what is
        above them may free them; the caller goes round again)."""
        plan = self.plan_restore_set(ids)
        every = list(
            dict.fromkeys(rid for root in plan.ready for rid in plan.groups[root])
        )
        if every:
            before = {r.id: self._snapshot(r) for r in self._records.list_by_ids(every)}
            self._records.restore_many(every)
            self._log_restored(every, before)
        back = set(every)
        # Held back, or waiting for a parent that was not deleted with them:
        # whatever is not live now is left for the next round.
        left = [str(i) for i in (*plan.blocked, *plan.waiting) if i not in back]
        return RestoreSetResultDTO(
            restored=len(plan.ready), came_back=len(every), left=left
        )

    def restore_records(
        self, ids: list[str], with_parents: bool = True
    ) -> RestoreSetResultDTO:
        """Restore exactly these deleted records and nothing else: not what was
        deleted alongside them, which is how a bulk delete of sixty records can
        be undone for three of them. A record under a deleted record comes back
        only with it, so with `with_parents` (the default) the deleted records
        above a chosen one come back too, each by itself; without it such a
        record is left. One held back by a deleted collection or schema is left
        either way. One lookup, one update and one history entry per record."""
        wanted: list[uuid.UUID] = []
        for raw in ids:
            try:
                wanted.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        chosen = {
            r.id: r
            for r in self._records.list_by_ids(list(dict.fromkeys(wanted)))
            if r.deleted_at is not None
        }
        coming = dict(chosen)
        if with_parents:
            frontier = {
                r.parent_record_id
                for r in chosen.values()
                if r.parent_record_id is not None
            }
            while frontier:
                found = [
                    p
                    for p in self._records.list_by_ids(list(frontier))
                    if p.deleted_at is not None and p.id not in coming
                ]
                coming.update({p.id: p for p in found})
                frontier = {
                    p.parent_record_id for p in found if p.parent_record_id is not None
                }
        blockers = self._restore_blockers(list(coming.values()))
        # A record can come back unless a deleted collection or schema holds it
        # or a deleted record above it is not itself coming back. Anything
        # dropped can hold others up, so go round until it settles.
        # Nor can one whose unique values were taken meanwhile.
        ok = set(coming) - set(self._restore_clashes(list(coming.values())))
        while True:
            held = {
                rid
                for rid in ok
                if (b := blockers[rid]) is not None
                and (b.kind != "record" or b.id not in ok)
            }
            if not held:
                break
            ok -= held
        every = [rid for rid in coming if rid in ok]
        if every:
            before = {r.id: self._snapshot(r) for r in self._records.list_by_ids(every)}
            self._records.restore_many(every)
            self._log_restored(every, before)
        return RestoreSetResultDTO(
            restored=len([rid for rid in every if rid in chosen]),
            came_back=len(every),
            left=[str(rid) for rid in chosen if rid not in ok],
        )

    def _restore_groups(
        self, records: list[RecordDTO]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """`_restore_group` for many deleted records at once: the subtrees are
        fetched together (a query per level) and each record's group is worked
        out in memory."""
        if not records:
            return {}
        levels = self._records.subtree_levels([r.id for r in records], deleted=True)
        every = list(dict.fromkeys(rid for level in levels for rid in level))
        rows = {r.id: r for r in self._records.list_by_ids(every)}
        children: dict[uuid.UUID, list[uuid.UUID]] = {}
        for row in rows.values():
            if row.parent_record_id is not None:
                children.setdefault(row.parent_record_id, []).append(row.id)
        groups: dict[uuid.UUID, list[uuid.UUID]] = {}
        for record in records:
            group = [record.id]
            pending = [record.id]
            while pending:
                for child in children.get(pending.pop(), []):
                    # Deleted with it: stamped with the same moment, reached
                    # through others in the group.
                    if rows[child].deleted_at == record.deleted_at:
                        group.append(child)
                        pending.append(child)
            groups[record.id] = group
        return groups

    def _restore_blockers(
        self, records: list[RecordDTO]
    ) -> dict[uuid.UUID, BlockerDTO | None]:
        """`_restore_blocker` for many records at once. Collections and schemas
        are looked up once each, and the records above them a level at a time.
        A record blocker carries no name (it takes a rendering per record);
        callers that need one use `restore_plan`."""
        datasets = {
            did: self._datasets.get_by_id(
                did, include_deleted=True, with_count=False, with_schemas=False
            )
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
        before = {r.id: self._snapshot(r) for r in self._records.list_by_ids(every)}
        self._records.restore_many(every)
        self._log_restored(every, before)
        return self.get(str(record.id))

    def _log_restored(
        self, every: list[uuid.UUID], before: dict[uuid.UUID, dict[str, Any]]
    ) -> None:
        """History for records just brought back: parents before what sits
        under them (a child can't come back under a parent still deleted, here
        or wherever the entries are applied next), each tree one action."""
        if not self._audit:
            return
        restored = _parents_first(self._records.list_by_ids(every))
        tree = _tree_actions(restored)
        with _audit_batch(self._audit, "restore", len(every) > 1):
            for record in restored:
                self._audit.log_change(
                    "restore",
                    "record",
                    record.id,
                    before[record.id],
                    self._snapshot(record),
                    op=tree[record.id],
                )

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
        if self._audit:
            stones = [
                (gone.id, tombstone(self._snapshot(gone)))
                for gone in self._records.list_by_ids(ids)
            ]
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
        levels = self._records.subtree_levels([record.id], deleted=None)
        every = [rid for level in levels for rid in level]
        self.purge_records(every)

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

    def _handle_referrers(self, target_ids: set[uuid.UUID], force: bool) -> None:
        """Block a delete of target_ids if anything outside the batch still
        references it, unless force=True -- in which case the referencing
        fields are cleared (ON DELETE SET NULL) and audit-logged instead."""
        referrers = self._find_referrers(target_ids, exclude_ids=target_ids)
        if not referrers:
            return
        if not force:
            raise ValidationError(_referrers_message(referrers))

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


def _parents_first(records: list[RecordDTO]) -> list[RecordDTO]:
    """`records` with each after the one among them it sits under."""
    by_id = {r.id: r for r in records}
    placed: set[uuid.UUID] = set()
    out: list[RecordDTO] = []

    def place(record: RecordDTO) -> None:
        if record.id in placed:
            return
        above = by_id.get(record.parent_record_id) if record.parent_record_id else None
        if above is not None:
            place(above)
        placed.add(record.id)
        out.append(record)

    for record in records:
        place(record)
    return out
