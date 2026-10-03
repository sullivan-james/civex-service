from __future__ import annotations

import dataclasses
import re
import uuid
from datetime import date as _date, datetime as _dt
from pathlib import Path
from typing import Any, Iterator

from civex.domain.dtos import (
    DatasetDTO,
    FieldDTO,
    FileRef,
    RecordDTO,
    ReferrerGroupDTO,
    ResolvedField,
    ResolvedSchema,
    SchemaDTO,
)
from civex.domain import geo as geo_domain
from civex.domain import partial_dates, templating, units
from civex.domain.exceptions import CoercionError, NotFoundError, ValidationError
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
    (name-keyed) field values. Falls back to the file's original name if no
    template is set, or if any referenced field is blank/unset — a
    partially-substituted name (e.g. "_.pdf") is worse than the original.
    `builtins` supplies `schema` and `id`; `ext` comes from the file.
    """
    if not template:
        return ref.filename
    ext = Path(ref.filename).suffix.lstrip(".")
    try:
        resolved = templating.render(
            template, field_values, {**(builtins or {}), "ext": ext}, "fallback"
        )
    except ValidationError:
        return ref.filename  # a template stored before the rules tightened
    if resolved is None:
        return ref.filename
    resolved = _UNSAFE_FILENAME_CHARS_RE.sub("_", resolved).strip()
    return resolved or ref.filename


# Keys the server adds to a file value in responses. They describe the moment
# of the read, so a client that echoes them back must not get them stored.
DERIVED_FILE_KEYS = ("resolved_filename", "location")


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
MAX_ZIP_TOTAL_SIZE = 500 * 1024 * 1024  # 500 MB, summed from stored FileRef.size


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


def _apply_filename_templates(
    data: dict[str, Any],
    fields: list[ResolvedField],
    builtins: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Annotate every file/file_list value in `data` with `resolved_filename`,
    derived from that field's `filename_template` restriction (if any)."""
    result = dict(data)
    for rf in fields:
        f = rf.field
        if f.dtype not in ("file", "file_list"):
            continue
        template = (f.restrictions or {}).get("filename_template")
        value = result.get(f.name)
        if isinstance(value, dict):
            result[f.name] = _with_resolved_filename(value, template, data, builtins)
        elif isinstance(value, list):
            result[f.name] = [
                _with_resolved_filename(item, template, data, builtins)
                if isinstance(item, dict)
                else item
                for item in value
            ]
    return result


# Types that skip the generic _COERCE path (handled explicitly in coerce_value)
# and are also excluded from natural-name computation (they're collection/blob types).
_SKIP_TYPES = {"reference", "reference_list", "file", "file_list", "tags", "geo"}


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
        if f.dtype in _SKIP_TYPES:
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
        return {shape.id_to_name.get(k, k): v for k, v in data.items()}

    def _with_names(
        self, dto: RecordDTO, shapes: SchemaResolver | None = None
    ) -> RecordDTO:
        """`dto` with name-keyed data and its natural name. Pass the
        operation's `shapes` when naming several records, so each schema is
        resolved once, not once per record."""
        shape = (shapes or self._schema_svc.resolver())(dto.schema_id)
        if shape is None:
            return dataclasses.replace(dto)
        named_data = {shape.id_to_name.get(k, k): v for k, v in dto.data.items()}
        builtins = _name_builtins(shape.schema.name, dto.id)
        natural_name = _natural_name(
            named_data, shape.fields, shape.schema.display_template, builtins
        )
        named_data = _apply_filename_templates(named_data, shape.fields, builtins)
        return dataclasses.replace(dto, data=named_data, natural_name=natural_name)

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
        return self._attach_file_locations(
            self._label_references(records, shapes), shapes
        )

    def _attach_file_locations(
        self, records: list[RecordDTO], shapes: SchemaResolver | None = None
    ) -> list[RecordDTO]:
        """Stamp every file/file_list value with `location`: the volume it is
        stored on, that volume's state, and whether it can be opened now. One
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

        volume_of = self._files.locate_volumes(wanted)
        status = {
            name: self._files.volume_status(name)
            for name in {v for v in volume_of.values() if v}
        }

        def location(sha: str | None) -> dict[str, Any]:
            volume = volume_of.get(sha or "")
            if volume is None:
                # Not on any volume we know of (yet): don't claim it is gone --
                # it may only be on a remote that hasn't been fetched.
                return {"volume": None, "state": "unknown", "available": None}
            st = status[volume]
            return {"volume": volume, "state": st.state, "available": st.reachable}

        def decorate(value: Any) -> Any:
            if isinstance(value, dict):
                return {**value, "location": location(value.get("sha256"))}
            if isinstance(value, list):
                return [decorate(item) for item in value]
            return value

        return [
            dataclasses.replace(
                r,
                data={
                    **r.data,
                    **{n: decorate(r.data.get(n)) for n in names if n in r.data},
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
            _check_restrictions(value, field.dtype, field.restrictions, name)

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
            if parent_record.dataset_id != dataset.id:
                raise ValidationError(
                    f"Parent record must belong to dataset '{dataset_name}'"
                )
            if parent_record.schema_id != schema.parent_id:
                expected_parent = self._schema_svc._repo.get_by_id(
                    schema.parent_id, include_deleted=True
                )
                raise ValidationError(
                    f"Parent record uses schema '{parent_record.schema_name}', "
                    f"expected '{expected_parent.name if expected_parent else schema.parent_id}'"
                )
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
            self._audit.log_change("create", "record", dto.id, None, named.to_dict())
        if self._job_svc:
            self._job_svc.trigger_for_record(named, "record_created", depth=_job_depth)
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
        self, record_id: str, data: dict[str, Any], _job_depth: int = 0
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
        dto = self._records.update(id=raw.id, data=id_data)
        named = self._with_names(dto, shapes)
        if self._audit:
            old_named = dataclasses.replace(
                raw, data=old_data, schema_name=named.schema_name
            )
            self._audit.log_change(
                "update", "record", raw.id, old_named.to_dict(), named.to_dict()
            )
        if self._job_svc:
            changed = {
                k
                for k in set(old_data) | set(named.data)
                if old_data.get(k) != named.data.get(k)
            }
            self._job_svc.trigger_for_record(
                named, "record_updated", changed_fields=changed, depth=_job_depth
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

    def _attach_derived(
        self, schema_name: str, records: list[RecordDTO], columns: list[str]
    ) -> list[RecordDTO]:
        """Fill `derived` with the requested columns a record's own data
        can't answer: fields inherited from an ancestor record, and
        `ref_field.target_field` joins. Ancestors and join targets are each
        batch-loaded once per level, not once per row. A column that no
        longer resolves (a field or target schema renamed after a view was
        saved) is left out rather than raised -- this runs at read time,
        long after create/update validation."""
        schema = self._schema_svc.get(schema_name)
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
            return records

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
            out.append(dataclasses.replace(record, derived=derived))
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
        if self._audit:
            for record in records:
                self._audit.log_change(
                    "delete", "record", record.id, record.to_dict(), None
                )
        self._records.delete_many(every)
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

    def restore(self, record_id: str) -> RecordDTO:
        """Undo delete(): the record and every descendant cascade-deleted
        with it become live again."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        if record.deleted_at is None:
            raise ValidationError(f"Record '{record_id}' is not deleted")
        levels = self._records.subtree_levels([record.id], deleted=True)
        every = [rid for level in levels for rid in level]
        before = {r.id: r for r in self._records.list_by_ids(every)}
        self._records.restore_many(every)
        if self._audit:
            shapes = self._schema_svc.resolver()
            for restored in self._records.list_by_ids(every):
                self._audit.log_change(
                    "restore",
                    "record",
                    restored.id,
                    before[restored.id].to_dict(),
                    self._with_names(restored, shapes).to_dict(),
                )
        return self.get(str(record.id))

    def purge(self, record_id: str) -> None:
        """Permanently remove a record (and its cascade-deleted descendants)
        that's already in Recently Deleted — a separate, explicit action
        from delete(). Irreversible."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        if record.deleted_at is None:
            raise ValidationError(
                f"Record '{record_id}' must be deleted before it can be purged"
            )
        levels = self._records.subtree_levels([record.id], deleted=None)
        every = [rid for level in levels for rid in level]
        if self._audit:
            shapes = self._schema_svc.resolver()
            for gone in self._records.list_by_ids(every):
                self._audit.log_change(
                    "purge",
                    "record",
                    gone.id,
                    self._with_names(gone, shapes).to_dict(),
                    None,
                )
        self._records.purge_many(every)

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
            old_named = self._with_names(rec)
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
                    old_named.to_dict(),
                    self._with_names(updated).to_dict(),
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
