from __future__ import annotations

import re
import uuid
from typing import Any

from civex.domain.dtos import (
    FieldDTO,
    NameIssue,
    ResolvedField,
    SchemaDeleteImpactDTO,
    SchemaDTO,
)
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain import geo as geo_domain
from civex.domain import partial_dates, units
from civex.domain.field_descriptors import (
    FIELD_TYPES,
    RestrictionDescriptor,
    restriction_keys,
)
from civex.domain.naming import is_slug, slugify, validate_name
from civex.domain.timezones import validate_timezone
from civex.repositories.protocols import (
    AuditRepository,
    RecordRepository,
    SchemaRepository,
)

VALID_DTYPES = frozenset(
    [
        "integer",
        "float",
        "string",
        "boolean",
        "file",
        "file_list",
        "reference",
        "date",
        "datetime",
        "enum",
        "url",
        "reference_list",
        "tags",
        "geo",
    ]
)

# Valid `restrictions` keys per dtype -- what RecordService._check_restrictions()
# actually reads. Anything else would be silently ignored at write time,
# letting a field look restricted in the UI while enforcing nothing, so unknown
# keys are rejected up front. Derived from the field descriptors, which are
# also what the web UI renders its editors from, so the two cannot drift.
VALID_RESTRICTION_KEYS: dict[str, frozenset[str]] = restriction_keys()


def _check_control_value(desc: RestrictionDescriptor, value: Any) -> None:
    """The shape every value of a given control has, whatever the type."""
    problem = None
    if desc.control == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problem = "a number"
    elif desc.control in ("integer", "bytes"):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            problem = "a whole number of at least 1"
    elif desc.control == "choices":
        if not isinstance(value, list) or not all(
            isinstance(c, str) and c.strip() for c in value
        ):
            problem = "a list of non-empty text values"
    elif desc.control in ("schema", "accept"):
        if not isinstance(value, str) or not value.strip():
            problem = "non-empty text"
    if problem:
        raise ValidationError(
            f"Restriction '{desc.key}' must be {problem}, got {value!r}"
        )


def _validate_restriction_values(dtype: str, restrictions: dict[str, Any]) -> None:
    """Values of the keys that carry structure: checked once, when the field
    is saved, so `_check_restrictions` can trust them."""
    for desc in FIELD_TYPES[dtype].restrictions if dtype in FIELD_TYPES else ():
        if desc.key in restrictions:
            _check_control_value(desc, restrictions[desc.key])
    if "unit" in restrictions:
        restrictions["unit"] = units.validate_symbol(restrictions["unit"])
    if "precision" in restrictions:
        if restrictions["precision"] not in partial_dates.PRECISIONS:
            raise ValidationError(
                f"Restriction 'precision' must be one of: "
                f"{', '.join(partial_dates.PRECISIONS)}"
            )
    if dtype == "date":
        for key in ("min", "max"):
            bound = restrictions.get(key)
            if bound is None:
                continue
            try:
                partial_dates.period(str(bound))
            except ValueError:
                raise ValidationError(
                    f"Restriction '{key}' must be a year, month or day "
                    f"(2020, 2020-03 or 2020-03-14), got {bound!r}"
                ) from None
    if "geometry_types" in restrictions:
        types = restrictions["geometry_types"]
        bad = (
            [t for t in types if t not in geo_domain.GEOMETRY_TYPES]
            if isinstance(types, list)
            else [types]
        )
        if bad or not types:
            raise ValidationError(
                f"Restriction 'geometry_types' must be a list drawn from: "
                f"{', '.join(geo_domain.GEOMETRY_TYPES)}"
            )
    if "bbox" in restrictions:
        restrictions["bbox"] = geo_domain.validate_bbox(restrictions["bbox"])


def _validate_restriction_keys(dtype: str, restrictions: dict[str, Any] | None) -> None:
    if not restrictions:
        return
    allowed = VALID_RESTRICTION_KEYS.get(dtype, frozenset())
    unknown = sorted(set(restrictions) - allowed)
    if unknown:
        valid = ", ".join(sorted(allowed)) if allowed else "(none)"
        raise ValidationError(
            f"Unknown restriction key(s) {unknown} for type '{dtype}'. Valid keys: {valid}"
        )
    _validate_restriction_values(dtype, restrictions)
    tz = restrictions.get("timezone")
    if tz is not None:
        # Stored verbatim and later handed to ZoneInfo, so it has to be exact.
        if not isinstance(tz, str) or validate_timezone(tz) != tz:
            raise ValidationError(
                f"Restriction 'timezone' must be an IANA zone name with no "
                f"surrounding whitespace, got {tz!r}"
            )


# `{field_name}` placeholders in a `filename_template` restriction; `{ext}`
# is the one reserved token that isn't a field name (see record_service.py).
TEMPLATE_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _validate_filename_template(
    restrictions: dict[str, Any] | None, known_field_names: set[str]
) -> None:
    template = (restrictions or {}).get("filename_template")
    if not template:
        return
    referenced = set(TEMPLATE_TOKEN_RE.findall(template)) - {"ext"}
    unknown = sorted(referenced - known_field_names)
    if unknown:
        raise ValidationError(
            f"filename_template references unknown field(s) {unknown}"
        )


def _suggest(name: str) -> str | None:
    """Slugified alternative for a legacy name, or None if nothing survives."""
    try:
        return slugify(name)
    except ValidationError:
        return None


class SchemaService:
    def __init__(
        self,
        repo: SchemaRepository,
        audit_repo: AuditRepository | None = None,
        record_repo: RecordRepository | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit_repo
        self._records = record_repo

    def create(
        self,
        name: str,
        description: str | None = None,
        parent: str | None = None,
        label: str | None = None,
        allow_legacy_name: bool = False,
    ) -> SchemaDTO:
        # allow_legacy_name is for restore/import paths only: a dump taken
        # before slug validation existed must round-trip byte-for-byte, and
        # silently slugifying its names would break the workflow YAML in the
        # same dump that references them.
        if not allow_legacy_name:
            validate_name(name, "schema name")
        if self._repo.get_by_name(name):
            raise AlreadyExistsError(f"Schema '{name}' already exists")

        parent_id: uuid.UUID | None = None
        if parent:
            parent_dto = self._repo.get_by_name(parent)
            if not parent_dto:
                raise NotFoundError(f"Parent schema '{parent}' not found")
            parent_id = parent_dto.id

        dto = self._repo.create(
            name=name,
            description=description,
            parent_id=parent_id,
            label=label or None,
        )
        if self._audit:
            self._audit.log_change("create", "schema", dto.id, None, dto.to_dict())
        return dto

    def create_with_fields(
        self,
        name: str,
        description: str | None = None,
        parent: str | None = None,
        fields: list[dict[str, Any]] | None = None,
        label: str | None = None,
    ) -> SchemaDTO:
        """Create a schema and all of its fields as one unit.

        Lets a single caller (e.g. the AI assistant's create_schema tool) produce
        one proposal/approval instead of one per field.
        """
        self.create(name, description=description, parent=parent, label=label)
        for f in fields or []:
            self.add_field(
                name,
                f["name"],
                f["type"],
                required=f.get("required", False),
                restrictions=f.get("restrictions"),
                default_value=f.get("default"),
                label=f.get("label"),
            )
        return self.get(name)

    def get(self, name: str) -> SchemaDTO:
        dto = self._repo.get_by_name(name)
        if not dto:
            raise NotFoundError(f"Schema '{name}' not found")
        return dto

    def list_all(self) -> list[SchemaDTO]:
        return self._repo.list_all()

    def add_field(
        self,
        schema_name: str,
        field_name: str,
        dtype: str,
        required: bool = False,
        restrictions: dict[str, Any] | None = None,
        default_value: Any = None,
        label: str | None = None,
        allow_legacy_name: bool = False,
    ) -> FieldDTO:
        if dtype not in VALID_DTYPES:
            raise ValueError(
                f"Unknown dtype '{dtype}'. Choose from: {', '.join(sorted(VALID_DTYPES))}"
            )
        _validate_restriction_keys(dtype, restrictions)
        if not allow_legacy_name:  # see create() for why restore opts out
            validate_name(field_name, "field name")

        schema = self.get(schema_name)

        if any(f.name == field_name for f in schema.fields):
            raise AlreadyExistsError(
                f"Field '{field_name}' already exists on schema '{schema_name}'"
            )

        known_field_names = {rf.field.name for rf in self.collect_fields(schema)}
        _validate_filename_template(restrictions, known_field_names)

        field = self._repo.add_field(
            schema_id=schema.id,
            name=field_name,
            dtype=dtype,
            required=required,
            restrictions=restrictions or {},
            default_value=default_value,
            label=label or None,
        )
        if self._audit:
            self._audit.log_change("create", "field", field.id, None, field.to_dict())
        return field

    def update(
        self,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
        display_fields=...,
        label=...,
    ) -> SchemaDTO:
        schema = self.get(name)
        if new_name and new_name != name:
            validate_name(new_name, "schema name")
            if self._repo.get_by_name(new_name):
                raise AlreadyExistsError(f"Schema '{new_name}' already exists")
        if display_fields is not ...:
            entries = list(display_fields or [])
            names = {rf.field.name for rf in self.collect_fields(schema)}
            unknown = [n for n in entries if n not in names]
            if unknown:
                raise NotFoundError(f"Field(s) {unknown} not found on schema '{name}'")
        old_dict = schema.to_dict()
        extra: dict[str, Any] = (
            {}
            if display_fields is ...
            else {"display_fields": list(display_fields or [])}
        )
        if label is not ...:
            extra["label"] = label or None
        updated = self._repo.update(
            schema.id, name=new_name, description=description, **extra
        )
        if self._audit:
            self._audit.log_change(
                "update", "schema", updated.id, old_dict, updated.to_dict()
            )
        return updated

    def _schemas_displaying_field(
        self, target_field: FieldDTO
    ) -> list[tuple[SchemaDTO, list[int]]]:
        """Every schema whose display_fields currently resolves at least one
        entry to `target_field` -- resolved by field identity (not just name),
        respecting name-shadowing in the inheritance chain, so a schema whose
        own field of the same name shadows an inherited `target_field` is
        correctly left out.

        Returns (schema, [indices into that schema's display_fields]) pairs.
        """
        results = []
        for schema in self._repo.list_all():
            if not schema.display_fields:
                continue
            resolved_by_name = {
                rf.field.name: rf.field.id for rf in self.collect_fields(schema)
            }
            indices = [
                i
                for i, entry_name in enumerate(schema.display_fields)
                if resolved_by_name.get(entry_name) == target_field.id
            ]
            if indices:
                results.append((schema, indices))
        return results

    def delete_field(self, schema_name: str, field_name: str) -> None:
        schema = self.get(schema_name)
        field = next((f for f in schema.fields if f.name == field_name), None)
        if field is None:
            raise NotFoundError(
                f"Field '{field_name}' not found on schema '{schema_name}'"
            )
        affected = self._schemas_displaying_field(field)
        if self._audit:
            self._audit.log_change("delete", "field", field.id, field.to_dict(), None)
        self._repo.delete_field(field.id)
        for affected_schema, indices in affected:
            remaining = [
                entry
                for i, entry in enumerate(affected_schema.display_fields)
                if i not in indices
            ]
            self._repo.update(
                affected_schema.id,
                name=None,
                description=None,
                display_fields=remaining,
            )

    def update_field(
        self,
        schema_name: str,
        field_name: str,
        *,
        new_name: str | None = None,
        required: bool | None = None,
        restrictions: dict | None = None,
        default_value: Any = ...,
        label: Any = ...,
    ) -> FieldDTO:
        schema = self.get(schema_name)
        field = next((f for f in schema.fields if f.name == field_name), None)
        if field is None:
            raise NotFoundError(
                f"Field '{field_name}' not found on schema '{schema_name}'"
            )
        renaming = bool(new_name and new_name != field_name)
        if renaming:
            assert new_name is not None  # implied by `renaming`
            validate_name(new_name, "field name")
            if any(f.name == new_name for f in schema.fields):
                raise AlreadyExistsError(
                    f"Field '{new_name}' already exists on schema '{schema_name}'"
                )
        if restrictions is not None:
            _validate_restriction_keys(field.dtype, restrictions)
            known_field_names = {rf.field.name for rf in self.collect_fields(schema)}
            _validate_filename_template(restrictions, known_field_names)
        old_dict = field.to_dict()
        kwargs: dict[str, Any] = dict(
            name=new_name, required=required, restrictions=restrictions
        )
        if default_value is not ...:
            kwargs["default_value"] = default_value
        if label is not ...:
            kwargs["label"] = label or None
        affected = self._schemas_displaying_field(field) if renaming else []
        updated = self._repo.update_field(field.id, **kwargs)
        for affected_schema, indices in affected:
            assert new_name is not None  # implied by `renaming`
            renamed = list(affected_schema.display_fields)
            for i in indices:
                renamed[i] = new_name
            self._repo.update(
                affected_schema.id, name=None, description=None, display_fields=renamed
            )
        if self._audit:
            self._audit.log_change(
                "update", "field", updated.id, old_dict, updated.to_dict()
            )
        return updated

    def reorder_fields(
        self, schema_name: str, field_ids: list[uuid.UUID]
    ) -> list[FieldDTO]:
        schema = self.get(schema_name)
        own_field_ids = {f.id for f in schema.fields}
        invalid = [fid for fid in field_ids if fid not in own_field_ids]
        if invalid:
            raise ValidationError(
                f"Field IDs not found on schema '{schema_name}': "
                + ", ".join(str(i) for i in invalid)
            )
        return self._repo.reorder_fields(schema.id, field_ids)

    def _children_by_parent(self) -> dict[uuid.UUID, list[SchemaDTO]]:
        by_parent: dict[uuid.UUID, list[SchemaDTO]] = {}
        for s in self._repo.list_all():
            if s.parent_id:
                by_parent.setdefault(s.parent_id, []).append(s)
        return by_parent

    def ancestors(self, schema: SchemaDTO) -> list[SchemaDTO]:
        """Parent, grandparent, ... -- nearest first. A soft-deleted ancestor
        still counts (see collect_fields): records keep pointing at it."""
        chain: list[SchemaDTO] = []
        current = schema
        while current.parent_id:
            parent = self._repo.get_by_id(current.parent_id, include_deleted=True)
            if parent is None:
                break
            chain.append(parent)
            current = parent
        return chain

    def descendants(self, schema: SchemaDTO) -> list[tuple[SchemaDTO, int]]:
        """Every schema that (transitively) inherits from `schema`, with its
        depth below it (children are 1), parents before their children."""
        by_parent = self._children_by_parent()
        found: list[tuple[SchemaDTO, int]] = []
        frontier = [(schema.id, 0)]
        while frontier:
            parent_id, depth = frontier.pop(0)
            for child in by_parent.get(parent_id, []):
                found.append((child, depth + 1))
                frontier.append((child.id, depth + 1))
        return found

    def _descendant_count(
        self, schema_id: uuid.UUID, children_by_parent: dict[uuid.UUID, list[SchemaDTO]]
    ) -> int:
        """How many schemas (transitively) inherit from schema_id. Purely
        informational for get_delete_impact() -- delete() does not touch
        them, see SchemaRepository.delete() -- but it's what blocks purge()
        until they're gone or repointed."""
        children = children_by_parent.get(schema_id, [])
        return len(children) + sum(
            self._descendant_count(c.id, children_by_parent) for c in children
        )

    def get_delete_impact(self, name: str) -> SchemaDeleteImpactDTO:
        """What deleting this schema would take with it: every record it
        types itself, across every collection -- the same set delete()
        actually moves to Recently Deleted, computed up front so the UI can
        warn before the delete happens. child_schema_count is informational
        only -- see _descendant_count."""
        schema = self.get(name)
        record_count = (
            len(self._records.list_ids_by_schema_ids([schema.id]))
            if self._records is not None
            else 0
        )
        return SchemaDeleteImpactDTO(
            child_schema_count=self._descendant_count(
                schema.id, self._children_by_parent()
            ),
            record_count=record_count,
        )

    def delete(self, name: str) -> None:
        """Soft-delete: the schema (and every record typed by it, across
        every collection — see SchemaRepository.delete) moves to Recently
        Deleted, reversible via restore() within the retention window.
        Schemas that inherit from this one are left untouched and keep
        resolving its fields; see docs/guides/deleting-and-restoring.md."""
        schema = self.get(name)
        if self._audit:
            self._audit.log_change(
                "delete", "schema", schema.id, schema.to_dict(), None
            )
        self._repo.delete(schema.id)

    def list_deleted(self) -> list[SchemaDTO]:
        return self._repo.list_deleted()

    def restore(self, name: str) -> SchemaDTO:
        """Undo delete(): the schema and the records cascade-deleted with it
        become live again (see SchemaRepository.restore)."""
        schema = self._repo.get_by_name(name, include_deleted=True)
        if schema is None:
            raise NotFoundError(f"Schema '{name}' not found")
        if schema.deleted_at is None:
            raise ValidationError(f"Schema '{name}' is not deleted")
        restored = self._repo.restore(schema.id)
        if self._audit:
            self._audit.log_change(
                "restore", "schema", restored.id, schema.to_dict(), restored.to_dict()
            )
        return restored

    def purge(self, name: str) -> None:
        """Permanently remove a schema that's already in Recently Deleted —
        a separate, explicit action from delete(). Irreversible."""
        schema = self._repo.get_by_name(name, include_deleted=True)
        if schema is None:
            raise NotFoundError(f"Schema '{name}' not found")
        if schema.deleted_at is None:
            raise ValidationError(
                f"Schema '{name}' must be deleted before it can be purged"
            )
        children = [s.name for s in self._repo.list_all() if s.parent_id == schema.id]
        if children:
            raise ValidationError(
                f"Cannot purge '{name}': schema(s) {children} still inherit from it. "
                "Delete or repoint them first."
            )
        if self._audit:
            self._audit.log_change("purge", "schema", schema.id, schema.to_dict(), None)
        self._repo.purge(schema.id)

    def name_to_id_map(self, schema: SchemaDTO) -> dict[str, str]:
        """field name → str(field.id), including inherited fields."""
        return {rf.field.name: str(rf.field.id) for rf in self.collect_fields(schema)}

    def id_to_name_map(self, schema: SchemaDTO) -> dict[str, str]:
        """str(field.id) → field name, including inherited fields."""
        return {str(rf.field.id): rf.field.name for rf in self.collect_fields(schema)}

    def lint_names(self) -> list[NameIssue]:
        """Every schema and field whose name isn't a valid slug.

        Slug validation is write-time only, so anything created before it
        existed keeps working; this is how a user finds those rows rather
        than discovering them when a workflow reference reads badly.
        """
        issues: list[NameIssue] = []
        for schema in self._repo.list_all():
            if not is_slug(schema.name):
                issues.append(
                    NameIssue(
                        kind="schema",
                        schema_name=schema.name,
                        name=schema.name,
                        suggestion=_suggest(schema.name),
                    )
                )
            for f in schema.fields:
                if not is_slug(f.name):
                    issues.append(
                        NameIssue(
                            kind="field",
                            schema_name=schema.name,
                            name=f.name,
                            suggestion=_suggest(f.name),
                        )
                    )
        return issues

    def collect_fields(self, schema: SchemaDTO) -> list[ResolvedField]:
        """
        Return all fields for a schema, including inherited ones.
        Own fields come first; parent fields follow (depth-first).
        Own fields shadow parent fields with the same name.
        """
        own = [
            ResolvedField(field=f, source_schema_name=schema.name)
            for f in schema.fields
        ]
        seen_names = {f.field.name for f in own}

        inherited: list[ResolvedField] = []
        if schema.parent_id:
            # include_deleted: a soft-deleted parent schema must keep
            # resolving here, or a live child schema would silently lose its
            # inherited fields the moment its parent is trashed (restorable,
            # not gone, until purged).
            parent = self._repo.get_by_id(schema.parent_id, include_deleted=True)
            if parent:
                for resolved in self.collect_fields(parent):
                    if resolved.field.name not in seen_names:
                        inherited.append(resolved)
                        seen_names.add(resolved.field.name)

        return own + inherited
