"""A bundle: a project's data as one file another civex can read.

A bundle is a zip holding `bundle.json` (what is in it: format, version,
schemas, collections, counts), `records.jsonl` (one record a line, so a
bundle's size is bounded by disk, not memory), the stored files its records
cite under `files/<sha256>` (optional), and the project's workflows and
plugins as the files they are. Record ids are kept, so parents and references
mean the same in the project it is read into, and a record already there (by
id) is left as it is.

This module is the pure part: the layout, the shapes, and what is checked
about them. `services/bundle_service.py` reads and writes the database.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

FORMAT = 1
"""The bundle layout this civex writes; a reader refuses a newer one."""

MANIFEST = "bundle.json"
RECORDS = "records.jsonl"
FILES_DIR = "files/"
WORKFLOWS_DIR = "workflows/"
PLUGINS_DIR = "plugins/"
EXTENSION = ".civex.zip"

# A workflow or plugin member keeps its own name inside the bundle: one plain
# file name, no folders, no dot-files, the right extension.
_MEMBER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
WORKFLOW_SUFFIXES = (".yaml", ".yml")
PLUGIN_SUFFIXES = (".py",)


class BundleError(ValueError):
    """The file is not a bundle this civex can read."""


@dataclass
class ExportOptions:
    """What goes into a bundle."""

    include_records: bool = True
    include_files: bool = True
    include_workflows: bool = True
    # Only these collections' records (and files); None = every collection.
    collections: list[str] | None = None


@dataclass
class BundleFiles:
    """What the bundle says about stored files."""

    included: bool
    count: int = 0
    bytes: int = 0
    # Files cited by records but not written: on no reachable drive at export.
    missing: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    """`bundle.json`: what a bundle holds, read before anything else."""

    format: int
    civex_version: str
    exported_at: str
    schemas: list[dict[str, Any]]
    collections: list[dict[str, Any]]
    records: int
    files: BundleFiles
    workflows: int
    plugins: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "civex_version": self.civex_version,
            "exported_at": self.exported_at,
            "schemas": self.schemas,
            "collections": self.collections,
            "records": self.records,
            "files": {
                "included": self.files.included,
                "count": self.files.count,
                "bytes": self.files.bytes,
                "missing": self.files.missing,
            },
            "workflows": self.workflows,
            "plugins": self.plugins,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Manifest":
        if not isinstance(raw, dict):
            raise BundleError("bundle.json is not an object")
        fmt = raw.get("format")
        if not isinstance(fmt, int):
            raise BundleError("bundle.json does not say its format")
        if fmt > FORMAT:
            raise BundleError(
                f"This bundle was written by a newer civex (format {fmt}); "
                "update civex to read it"
            )
        files_raw = raw.get("files") or {}
        if not isinstance(files_raw, dict):
            raise BundleError("bundle.json: 'files' is not an object")
        schemas = raw.get("schemas") or []
        collections = raw.get("collections") or []
        if not isinstance(schemas, list) or not isinstance(collections, list):
            raise BundleError("bundle.json: schemas and collections must be lists")
        for s in schemas:
            if not isinstance(s, dict) or not isinstance(s.get("name"), str):
                raise BundleError("bundle.json: a schema has no name")
        for c in collections:
            if not isinstance(c, dict) or not isinstance(c.get("name"), str):
                raise BundleError("bundle.json: a collection has no name")
        return cls(
            format=fmt,
            civex_version=str(raw.get("civex_version") or ""),
            exported_at=str(raw.get("exported_at") or ""),
            schemas=schemas,
            collections=collections,
            records=int(raw.get("records") or 0),
            files=BundleFiles(
                included=bool(files_raw.get("included", False)),
                count=int(files_raw.get("count") or 0),
                bytes=int(files_raw.get("bytes") or 0),
                missing=[str(s) for s in files_raw.get("missing") or []],
            ),
            workflows=int(raw.get("workflows") or 0),
            plugins=int(raw.get("plugins") or 0),
        )


@dataclass
class RecordLine:
    """One line of `records.jsonl`."""

    id: uuid.UUID
    collection: str
    schema: str
    parent: uuid.UUID | None
    data: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None

    def to_json(self) -> str:
        line: dict[str, Any] = {
            "id": str(self.id),
            "collection": self.collection,
            "schema": self.schema,
            "parent": str(self.parent) if self.parent else None,
            "data": self.data,
        }
        if self.created_at:
            line["created_at"] = self.created_at
        if self.updated_at:
            line["updated_at"] = self.updated_at
        return json.dumps(line, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def parse(cls, text: str) -> "RecordLine":
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise BundleError(f"records.jsonl: a line is not JSON ({e})") from None
        if not isinstance(raw, dict):
            raise BundleError("records.jsonl: a line is not an object")
        try:
            record_id = uuid.UUID(str(raw["id"]))
            parent = uuid.UUID(str(raw["parent"])) if raw.get("parent") else None
        except (KeyError, ValueError):
            raise BundleError("records.jsonl: a record's ids are not valid") from None
        collection, schema = raw.get("collection"), raw.get("schema")
        if not isinstance(collection, str) or not isinstance(schema, str):
            raise BundleError(
                "records.jsonl: a record names no collection or no schema"
            )
        data = raw.get("data")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise BundleError("records.jsonl: a record's values are not an object")
        return cls(
            id=record_id,
            collection=collection,
            schema=schema,
            parent=parent,
            data=data,
            created_at=raw.get("created_at") or None,
            updated_at=raw.get("updated_at") or None,
        )


def file_refs(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The stored files a record's values cite (`file` and `file_list`
    values), as the FileRef dicts they are."""
    refs: list[dict[str, Any]] = []
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("sha256"), str):
            refs.append(value)
        elif isinstance(value, list):
            refs.extend(
                v
                for v in value
                if isinstance(v, dict) and isinstance(v.get("sha256"), str)
            )
    return refs


def sort_schemas(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parents before children, so each can be made in turn."""
    by_name = {s["name"]: s for s in schemas}
    result: list[dict[str, Any]] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        parent = by_name[name].get("parent")
        if parent and parent in by_name:
            visit(parent)
        result.append(by_name[name])

    for s in schemas:
        visit(s["name"])
    return result


def member_name_problem(name: str, suffixes: Iterable[str]) -> str | None:
    """Why a workflow or plugin can't be written under `name` in the project
    (a path, a dot-file, the wrong kind of file), or None when it can."""
    if not _MEMBER_NAME.match(name) or name.startswith("."):
        return "its name is not a plain file name"
    if not name.lower().endswith(tuple(suffixes)):
        return f"it is not a {'/'.join(suffixes)} file"
    return None
