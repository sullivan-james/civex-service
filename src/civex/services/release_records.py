"""A release's records as `FileAccessService` reads them.

`FileAccessService` reads records through a small set of `RecordService`
calls (`get_many`, `get`, `file_values`, `ancestor_trails`, `stream_records`,
`count_records`, `beneath`, `with_derived`). `FrozenRecords` answers the same
calls from a release's bundle (its `records.jsonl` and the schemas it was made
with), so the one path rule, plan, folder export, move and zip lay out a
release's files exactly as they lay out the live records': a release is just
another source of records. Where each file is comes from the release's own
pointer (`file_references.release_id`), stamped as the `location` a live
record's file value carries (`RecordService.locate_pointed`).

Only the records (a few hundred bytes each) are held in memory; files are
never read here.
"""

from __future__ import annotations

import json
import uuid
import zipfile
from datetime import datetime, timezone
from typing import IO, Any, Callable, Iterator

from civex.domain import bundle as spec
from civex.domain import templating
from civex.domain.dtos import RecordDTO
from civex.domain.exceptions import NotFoundError
from civex.domain.query import RecordQuery

_NS = uuid.UUID("6f0e3c1a-9d4b-4f57-8a2e-1c7b5d9e0f31")
_FILE_DTYPES = ("file", "file_list")


class FrozenRecords:
    def __init__(
        self,
        bundle: IO[bytes],
        locate: Callable[[set[str]], Callable[[str], dict[str, Any]]],
    ) -> None:
        """`bundle`: the release's bundle, open for reading. `locate`: given
        the files cited, where each is (`location`), from the release's own
        pointers."""
        with zipfile.ZipFile(bundle) as zf:
            manifest = json.loads(zf.read(spec.MANIFEST))
            lines = []
            if spec.RECORDS in zf.namelist():
                with zf.open(spec.RECORDS) as f:
                    lines = [json.loads(raw) for raw in f if raw.strip()]
        schemas = {s["name"]: s for s in manifest.get("schemas") or []}
        self._fields: dict[str, list[dict[str, Any]]] = {
            name: self._collect(schemas, name) for name in schemas
        }
        self._templates = {
            name: s.get("display_template") for name, s in schemas.items()
        }
        cited = {
            ref["sha256"]
            for line in lines
            for ref in spec.file_refs(spec.plain_data(line.get("data") or {}))
        }
        where = locate(cited)
        self._by_id: dict[uuid.UUID, RecordDTO] = {}
        self._order: list[uuid.UUID] = []
        for line in lines:
            record = self._record(line, where)
            self._by_id[record.id] = record
            self._order.append(record.id)

    # -- what FileAccessService asks ------------------------------------------

    @property
    def ids(self) -> list[str]:
        return [str(i) for i in self._order]

    def get(self, record_id: str) -> RecordDTO:
        try:
            return self._by_id[uuid.UUID(str(record_id))]
        except (KeyError, ValueError):
            raise NotFoundError(f"Record '{record_id}' is not in this release")

    def get_many(
        self, record_ids: list[str], as_stored: bool = False
    ) -> list[RecordDTO]:
        out = []
        for raw in dict.fromkeys(record_ids):
            try:
                found = self._by_id.get(uuid.UUID(str(raw)))
            except ValueError:
                continue
            if found is not None:
                out.append(found)
        return out

    def stream_records(
        self, query: RecordQuery, page_size: int = 500, **_: Any
    ) -> Iterator[list[RecordDTO]]:
        chosen = [
            self._by_id[i]
            for i in self._order
            if (query.schema is None or self._by_id[i].schema_name == query.schema)
        ]
        for at in range(0, len(chosen), page_size):
            yield chosen[at : at + page_size]

    def count_records(self, query: RecordQuery) -> int:
        return sum(len(page) for page in self.stream_records(query))

    def ancestor_trails(
        self, records: list[RecordDTO]
    ) -> dict[uuid.UUID, list[RecordDTO]]:
        trails: dict[uuid.UUID, list[RecordDTO]] = {}
        for r in records:
            chain: list[RecordDTO] = []
            parent = r.parent_record_id
            while parent is not None and parent in self._by_id and len(chain) < 64:
                chain.append(self._by_id[parent])
                parent = self._by_id[parent].parent_record_id
            trails[r.id] = chain[::-1]
        return trails

    def held_files(self, picked: Any, search: str | None = None) -> list[Any]:
        """Every file the release's records hold, as the inventory lists them
        (`FileAccessService` over a live project asks the database; a release
        has its records in hand). Where a file is comes from its `location`."""
        from civex.domain.file_access import HeldFile

        needle = (search or "").casefold()
        kinds = set(picked.kinds) if getattr(picked, "kinds", None) else None
        wanted = set(picked.ids) if getattr(picked, "ids", None) else None
        records = [
            self._by_id[i]
            for i in self._order
            if (kinds is None or self._by_id[i].schema_name in kinds)
            and (wanted is None or str(i) in {str(w) for w in wanted})
        ]
        values, _ = self.file_values(records)
        out = []
        for r, name, ref in values:
            filename = str(ref.get("filename") or "")
            out.append(
                HeldFile(
                    str(r.id),
                    str(r.dataset_id),
                    str(r.created_at),
                    name,
                    ref["sha256"],
                    filename,
                    int(ref.get("size") or 0),
                    (ref.get("location") or {}).get("volume") or None,
                    (),
                    False,
                    False,
                    not needle or needle in filename.casefold(),
                )
            )
        return out

    def files_from_server(self) -> bool:
        return False  # a release is read from its bundle, never from a server

    def shared_copies(self) -> dict[tuple[str, str | None], int]:
        return {}

    def recently_received(self, cited: Any) -> set[Any]:
        return set()

    def holding_files(self, picked: Any) -> list[str]:
        held = {h.record_id for h in self.held_files(picked)}
        return [i for i in self.ids if i in held]

    def beneath(self, records: list[RecordDTO], *_: Any, **__: Any) -> list[RecordDTO]:
        wanted = {r.id for r in records}
        out = []
        for i in self._order:
            r = self._by_id[i]
            parent = r.parent_record_id
            while parent is not None:
                if parent in wanted:
                    out.append(r)
                    break
                above = self._by_id.get(parent)
                parent = above.parent_record_id if above else None
        return out

    def with_derived(
        self, kind: str, records: list[RecordDTO], *_: Any, **__: Any
    ) -> list[RecordDTO]:
        return records

    def file_values(
        self, records: list[RecordDTO], field_names: list[str] | None = None
    ) -> tuple[list[tuple[RecordDTO, str, dict[str, Any]]], set[str]]:
        wanted = set(field_names) if field_names is not None else None
        known: set[str] = set()
        out: list[tuple[RecordDTO, str, dict[str, Any]]] = []
        for r in records:
            for f in self._fields.get(r.schema_name, []):
                if f.get("type") not in _FILE_DTYPES:
                    continue
                name = f["name"]
                known.add(name)
                if wanted is not None and name not in wanted:
                    continue
                value = r.data.get(name)
                items = value if isinstance(value, list) else [value]
                out.extend(
                    (r, name, ref)
                    for ref in items
                    if isinstance(ref, dict) and ref.get("sha256")
                )
        return out, known

    # -- building --------------------------------------------------------------

    @staticmethod
    def _collect(schemas: dict[str, Any], name: str) -> list[dict[str, Any]]:
        """A frozen schema's fields, its own then those above it."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        at: str | None = name
        while at and at in schemas and at not in seen:
            seen.add(at)
            out += list(schemas[at].get("fields") or [])
            at = schemas[at].get("parent")
        return out

    def _record(
        self, line: dict[str, Any], where: Callable[[str], dict[str, Any]]
    ) -> RecordDTO:
        data = spec.plain_data(line.get("data") or {})
        schema = str(line.get("schema") or "")

        def stamp(value: Any) -> Any:
            if isinstance(value, dict) and value.get("sha256"):
                return {**value, "location": where(value["sha256"])}
            if isinstance(value, list):
                return [stamp(v) for v in value]
            return value

        files = {
            f["name"]
            for f in self._fields.get(schema, [])
            if f.get("type") in _FILE_DTYPES
        }
        data = {k: stamp(v) if k in files else v for k, v in data.items()}
        collection = str(line.get("collection") or "")
        made = _when(line.get("created_at"))
        return RecordDTO(
            id=uuid.UUID(str(line["id"])),
            dataset_id=uuid.uuid5(_NS, "collection:" + collection),
            schema_id=uuid.uuid5(_NS, "schema:" + schema),
            schema_name=schema,
            parent_record_id=(
                uuid.UUID(str(line["parent"])) if line.get("parent") else None
            ),
            data=data,
            created_at=made,
            updated_at=_when(line.get("updated_at")) or made,
            natural_name=self._name(schema, data, line),
            dataset_name=collection,
        )

    def _name(
        self, schema: str, data: dict[str, Any], line: dict[str, Any]
    ) -> str | None:
        """The record's name by the template it was made with (the first
        nameable value without one), as `RecordService` names a live one."""
        builtins = {"schema": schema, "id": str(line.get("id") or "")[:8]}
        template = self._templates.get(schema)
        if template:
            try:
                return (
                    templating.render(template, data, builtins, on_missing="skip")
                    or None
                )
            except Exception:  # a template this civex can't read: no name
                return None
        for f in self._fields.get(schema, []):
            if f.get("type") in templating.UNNAMEABLE_DTYPES:
                continue
            value = data.get(f["name"])
            if value not in (None, "", []):
                return str(value)
        return None


def _when(raw: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
