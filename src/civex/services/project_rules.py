"""The rules a project holds whatever made the change.

A person's edit on one machine is checked by the service that makes it: a
collection can't drop a schema it still has records of, a unique key can't be
set while records share it, a naming template can only use fields that exist.
A change from another device was checked on *that* device, against what it
held then; by the time an authority takes it, other changes may have gone in
(the field the template uses was renamed elsewhere, a duplicate was added).
So the authority asks these rules again about whatever the change touched,
after writing it and before keeping it, and refuses it if the project would no
longer be one a single machine could hold.

The rules are the ones the services enforce on an edit, stated about a state
rather than a step: they are checked here, never re-implemented elsewhere.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from civex.domain.dtos import SchemaDTO
from civex.domain.exceptions import ValidationError
from civex.domain.templating import referenced_names
from civex.repositories.protocols import DatasetRepository, RecordRepository
from civex.services.schema_service import SchemaService

# Names a template may use without a field of that name.
_RECORD_BUILTINS = frozenset({"schema", "id"})
_FILE_BUILTINS = _RECORD_BUILTINS | {"ext"}


class ProjectRules:
    def __init__(
        self,
        schemas: SchemaService,
        datasets: DatasetRepository,
        records: RecordRepository,
    ) -> None:
        self._schemas = schemas
        self._datasets = datasets
        self._records = records

    def check(self, touched: Iterable[tuple[str, uuid.UUID]]) -> None:
        """Raise ValidationError, saying what would be wrong, if what these
        things are now breaks a rule. `touched` is (kind, id) of what changed."""
        schema_ids: set[uuid.UUID] = set()
        dataset_ids: set[uuid.UUID] = set()
        for kind, thing in touched:
            if kind == "schema":
                schema_ids.add(thing)
            elif kind == "field":
                found = self._schemas.find_fields({thing}).get(thing)
                if found is not None:
                    schema_ids.add(found[0].schema_id)
            elif kind == "dataset":
                dataset_ids.add(thing)
        for schema_id in list(schema_ids):
            schema = self._schemas.get_by_id(schema_id, include_deleted=True)
            if schema is not None:
                # Templates below it can use its fields.
                schema_ids |= {d.id for d, _ in self._schemas.descendants(schema)}
        for schema_id in schema_ids:
            schema = self._schemas.get_by_id(schema_id, include_deleted=True)
            if schema is not None and schema.deleted_at is None:
                self._check_schema(schema)
        for dataset_id in dataset_ids:
            self._check_collection(dataset_id)

    def _check_schema(self, schema: SchemaDTO) -> None:
        names = {rf.field.name for rf in self._schemas.collect_fields(schema)}
        if schema.display_template:
            missing = _missing(schema.display_template, names, _RECORD_BUILTINS)
            if missing:
                raise ValidationError(
                    f"The record name of '{schema.name}' would use "
                    f"{_listed(missing)}, which it no longer has"
                )
        for field in schema.fields:
            template = (field.restrictions or {}).get("filename_template")
            if isinstance(template, str) and template:
                missing = _missing(template, names, _FILE_BUILTINS)
                if missing:
                    raise ValidationError(
                        f"The file names of '{schema.name}.{field.name}' would use "
                        f"{_listed(missing)}, which it no longer has"
                    )
        own = {str(f.id) for f in schema.fields}
        for key in schema.unique_keys or []:
            if any(fid not in own for fid in key):
                raise ValidationError(
                    f"A uniqueness rule of '{schema.name}' would name a field it "
                    "no longer has"
                )
            if self._records.key_duplicates(schema.id, list(key)):
                raise ValidationError(
                    f"Records of '{schema.name}' already share the values a "
                    "uniqueness rule would make unique"
                )

    def _check_collection(self, dataset_id: uuid.UUID) -> None:
        dataset = self._datasets.get_by_id(
            dataset_id, include_deleted=True, with_count=False
        )
        if dataset is None or dataset.deleted_at is not None:
            return
        listed = {uuid.UUID(str(s)) for s in dataset.schema_ids or []}
        for schema_id in self._records.live_schema_ids(dataset.id) - listed:
            schema = self._schemas.get_by_id(schema_id, include_deleted=True)
            raise ValidationError(
                f"Collection '{dataset.name}' would no longer allow "
                f"'{schema.name if schema else schema_id}', and it still has "
                "records of it"
            )
        for schema_id in listed:
            schema = self._schemas.get_by_id(schema_id, include_deleted=True)
            if schema is None or schema.deleted_at is not None:
                continue
            for ancestor in self._schemas.ancestors(schema):
                if ancestor.id not in listed:
                    raise ValidationError(
                        f"Collection '{dataset.name}' would allow '{schema.name}' "
                        f"but not '{ancestor.name}', which it sits under"
                    )


def _missing(template: str, names: set[str], builtins: frozenset[str]) -> list[str]:
    """Names a template uses that are neither a field nor built in. A reach
    through a reference (`ref.field`) is checked by its first part."""
    try:
        used = referenced_names(template)
    except ValueError:
        return []  # not a template that can be read: not this rule's to judge
    return sorted({n for n in used if n.split(".", 1)[0] not in names | builtins})


def _listed(names: list[str]) -> str:
    return ", ".join(f"'{n}'" for n in names)
