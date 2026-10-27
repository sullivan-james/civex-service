"""Writing a project's bundle and reading one into a project.

One rule for `civex bundle export|import`, `GET /bundle`, `POST /bundle/import`
and the app. A bundle (`domain/bundle.py`) is a zip: `bundle.json`,
`records.jsonl` written a page of records at a time, the stored files its
records cite (optional), and the project's workflows and plugins.

Reading one in: schemas by name (one already here only gains the fields it
lacks), collections by name (one already here is reused), records by id (one
already here, live or deleted, is left as it is), each record through
`RecordService.add` so it is checked, in the history and synced like any
other, and the whole import is one event in Activity. A record is written
only once the record it sits inside and the records it references are here,
whatever order the bundle lists them in; one whose parent or target never
arrives is reported, not half written. Files are stored through the file
service, so placement and de-duplication apply, and a file whose bytes don't
hash to their name is refused.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from civex import __version__
from civex.domain import bundle as spec
from civex.domain.bundle import (
    BundleError,
    BundleFiles,
    ExportOptions,
    Manifest,
    RecordLine,
)
from civex.domain.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.services.dataset_service import DatasetService
from civex.services.file_service import FileService
from civex.services.progress import Progress
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService

# Records written per commit while importing: a commit per record made a large
# import dominated by fsyncs.
IMPORT_BATCH = 1000
# How many skipped records an import result names (the count is exact).
MAX_REPORTED = 200
_CHUNK = 1024 * 1024


@dataclass
class BundlePlan:
    """What a bundle would (or does) hold."""

    schemas: int = 0
    collections: list[str] = field(default_factory=list)
    records: int = 0
    files: int = 0
    file_bytes: int = 0
    # Files cited by the records but on no reachable drive here.
    files_unreachable: int = 0
    workflows: int = 0
    plugins: int = 0
    include_files: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemas": self.schemas,
            "collections": list(self.collections),
            "records": self.records,
            "files": self.files,
            "file_bytes": self.file_bytes,
            "files_unreachable": self.files_unreachable,
            "workflows": self.workflows,
            "plugins": self.plugins,
            "include_files": self.include_files,
        }


@dataclass
class Skipped:
    """A record (or workflow, plugin) the import left out, and why."""

    id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "reason": self.reason}


@dataclass
class ImportResult:
    schemas_new: int = 0
    schemas_existing: list[str] = field(default_factory=list)
    collections_new: int = 0
    collections_existing: list[str] = field(default_factory=list)
    records_added: int = 0
    records_existing: int = 0
    records_skipped: int = 0
    skipped: list[Skipped] = field(default_factory=list)
    files_added: int = 0
    # Files the records cite that the bundle did not carry and this project
    # hasn't got: the records keep citing them, and their location says so.
    files_missing: int = 0
    # Files in the bundle whose bytes don't hash to their name: not stored.
    files_refused: int = 0
    workflows: int = 0
    plugins: int = 0
    members_skipped: list[Skipped] = field(default_factory=list)

    def note(self, record_id: str, reason: str) -> None:
        self.records_skipped += 1
        if len(self.skipped) < MAX_REPORTED:
            self.skipped.append(Skipped(record_id, reason))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemas_new": self.schemas_new,
            "schemas_existing": list(self.schemas_existing),
            "collections_new": self.collections_new,
            "collections_existing": list(self.collections_existing),
            "records_added": self.records_added,
            "records_existing": self.records_existing,
            "records_skipped": self.records_skipped,
            "skipped": [s.to_dict() for s in self.skipped],
            "files_added": self.files_added,
            "files_missing": self.files_missing,
            "files_refused": self.files_refused,
            "workflows": self.workflows,
            "plugins": self.plugins,
            "members_skipped": [s.to_dict() for s in self.members_skipped],
        }


class BundleService:
    def __init__(
        self,
        schema_svc: SchemaService,
        dataset_svc: DatasetService,
        record_svc: RecordService,
        file_svc: FileService,
        commit: Callable[[], None],
        civex_dir: Path | None,
        batch: Callable[..., Any] | None = None,
    ) -> None:
        self._schemas = schema_svc
        self._datasets = dataset_svc
        self._records = record_svc
        self._files = file_svc
        self._commit = commit
        self._civex_dir = civex_dir
        # `history_svc.batch`: everything an import writes is one event.
        self._batch = batch

    # -- export ------------------------------------------------------------

    def plan_export(self, options: ExportOptions | None = None) -> BundlePlan:
        """What `export` would write, without writing it: the same walk over
        the records, so the counts can't disagree."""
        options = options or ExportOptions()
        plan, _, _ = self._walk(options, sink=None)
        return plan

    def export(
        self,
        path: Path,
        options: ExportOptions | None = None,
        progress: Progress | None = None,
    ) -> BundlePlan:
        """Write the bundle to `path` and say what went in."""
        options = options or ExportOptions()
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            plan, schemas, collections = self._walk(options, sink=zf, progress=progress)
            refs = self._cited  # set by _walk
            missing: list[str] = []
            if options.include_files and refs:
                if progress:
                    progress.phase("Adding files", len(refs), plan.file_bytes)
                written = 0
                for sha, size in refs.items():
                    if not self._write_file(zf, sha):
                        missing.append(sha)
                    written += 1
                    if progress:
                        progress.advance(written)
                        progress.add_bytes(size)
            plan.files_unreachable = len(missing)
            workflows = plugins = 0
            if options.include_workflows and self._civex_dir:
                workflows = self._add_members(
                    zf,
                    self._civex_dir / "workflows",
                    spec.WORKFLOWS_DIR,
                    spec.WORKFLOW_SUFFIXES,
                )
                plugins = self._add_members(
                    zf,
                    self._civex_dir / "plugins",
                    spec.PLUGINS_DIR,
                    spec.PLUGIN_SUFFIXES,
                )
            plan.workflows, plan.plugins = workflows, plugins
            manifest = Manifest(
                format=spec.FORMAT,
                civex_version=__version__,
                exported_at=datetime.now(timezone.utc).isoformat(),
                schemas=schemas,
                collections=collections,
                records=plan.records,
                files=BundleFiles(
                    included=options.include_files,
                    count=plan.files - len(missing) if options.include_files else 0,
                    bytes=plan.file_bytes,
                    missing=missing,
                ),
                workflows=workflows,
                plugins=plugins,
            )
            zf.writestr(spec.MANIFEST, json.dumps(manifest.to_dict(), indent=1))
        return plan

    def _walk(
        self,
        options: ExportOptions,
        sink: zipfile.ZipFile | None,
        progress: Progress | None = None,
    ) -> tuple[BundlePlan, list[dict[str, Any]], list[dict[str, Any]]]:
        """Count (and, with a `sink`, write) the records: one pass, a page at a
        time. Sets `self._cited` to the files they cite (sha -> size)."""
        plan = BundlePlan(include_files=options.include_files)
        schemas = self._export_schemas()
        plan.schemas = len(schemas)
        datasets = (
            self._selected_collections(options) if options.include_records else []
        )
        collections = [
            {
                "name": d.name,
                "description": d.description,
                "scope": d.scope,
                "timezone": d.timezone,
            }
            for d in datasets
        ]
        plan.collections = [d.name for d in datasets]
        cited: dict[str, int] = {}
        total = sum(d.record_count for d in datasets)
        if progress:
            progress.phase("Writing records", total)
        out = (
            sink.open(spec.RECORDS, "w", force_zip64=True)
            if sink and options.include_records
            else None
        )
        try:
            for dataset in datasets:
                for page in self._records.iter_find(dataset.name):
                    for record in page:
                        for ref in spec.file_refs(record.data):
                            cited.setdefault(ref["sha256"], int(ref.get("size") or 0))
                        if out is not None:
                            line = RecordLine(
                                id=record.id,
                                collection=dataset.name,
                                schema=record.schema_name,
                                parent=record.parent_record_id,
                                data=record.data,
                                created_at=record.created_at.isoformat(),
                                updated_at=record.updated_at.isoformat(),
                            )
                            out.write((line.to_json() + "\n").encode("utf-8"))
                    plan.records += len(page)
                    if progress:
                        progress.advance(plan.records)
        finally:
            if out is not None:
                out.close()
        plan.files = len(cited)
        plan.file_bytes = sum(cited.values())
        if options.include_files and sink is None:
            plan.files_unreachable = sum(
                1 for sha in cited if not self._files.exists(sha)
            )
        self._cited = cited
        if self._civex_dir and options.include_workflows:
            plan.workflows = len(
                self._members(self._civex_dir / "workflows", spec.WORKFLOW_SUFFIXES)
            )
            plan.plugins = len(
                self._members(self._civex_dir / "plugins", spec.PLUGIN_SUFFIXES)
            )
        return plan, schemas, collections

    def _selected_collections(self, options: ExportOptions):
        every = self._datasets.list_all(with_count=True)
        if options.collections is None:
            return every
        by_name = {d.name: d for d in every}
        missing = [n for n in options.collections if n not in by_name]
        if missing:
            raise NotFoundError(f"Collection '{missing[0]}' not found")
        return [by_name[n] for n in options.collections]

    def _export_schemas(self) -> list[dict[str, Any]]:
        schemas = self._schemas.list_all()
        names = {s.id: s.name for s in schemas}
        return spec.sort_schemas(
            [
                {
                    "name": s.name,
                    "label": s.label,
                    "description": s.description,
                    "parent": names.get(s.parent_id) if s.parent_id else None,
                    "display_template": s.display_template,
                    "unique_keys": s.unique_key_names,
                    "fields": [
                        {
                            "name": f.name,
                            "label": f.label,
                            "type": f.dtype,
                            "required": f.required,
                            "restrictions": f.restrictions,
                            "default_value": f.default_value,
                        }
                        for f in s.fields
                    ],
                }
                for s in schemas
            ]
        )

    def _write_file(self, zf: zipfile.ZipFile, sha: str) -> bool:
        """Copy one stored file into the bundle, uncompressed (media rarely
        compresses, and this keeps the import a plain copy). False when its
        bytes can't be read here (on no drive, or one that isn't reachable)."""
        try:
            chunks = self._files.stream(sha)
            first = next(chunks, b"")
        except (FileNotFoundError, OSError, VolumeUnavailableError):
            return False
        info = zipfile.ZipInfo(spec.FILES_DIR + sha)
        info.compress_type = zipfile.ZIP_STORED
        try:
            with zf.open(info, "w", force_zip64=True) as out:
                out.write(first)
                for chunk in chunks:
                    out.write(chunk)
        except (FileNotFoundError, OSError, VolumeUnavailableError):
            return False
        return True

    @staticmethod
    def _members(directory: Path, suffixes: tuple[str, ...]) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(
            p
            for p in directory.iterdir()
            if p.is_file()
            and p.suffix.lower() in suffixes
            and spec.member_name_problem(p.name, suffixes) is None
        )

    def _add_members(
        self,
        zf: zipfile.ZipFile,
        directory: Path,
        prefix: str,
        suffixes: tuple[str, ...],
    ) -> int:
        members = self._members(directory, suffixes)
        for p in members:
            zf.write(p, prefix + p.name)
        return len(members)

    # -- import ------------------------------------------------------------

    def inspect(self, path: Path) -> Manifest:
        """What a bundle holds, read before deciding to import it."""
        with self._open(path) as zf:
            return self._manifest(zf)

    def import_bundle(
        self,
        path: Path,
        progress: Progress | None = None,
        label: str | None = None,
    ) -> ImportResult:
        """Read a bundle into this project. See the module docstring for what
        is new, what is reused and what is left out."""
        result = ImportResult()
        with self._open(path) as zf:
            manifest = self._manifest(zf)
            if self._batch is not None:
                with self._batch("import", label or path.name):
                    self._import(zf, manifest, result, progress)
            else:
                self._import(zf, manifest, result, progress)
        return result

    def _import(
        self,
        zf: zipfile.ZipFile,
        manifest: Manifest,
        result: ImportResult,
        progress: Progress | None,
    ) -> None:
        self._import_schemas(manifest.schemas, result)
        self._import_collections(manifest.collections, result)
        if spec.RECORDS in zf.namelist():
            self._import_records(zf, manifest, result, progress)
        self._import_members(zf, result)

    def _import_schemas(
        self, schemas: list[dict[str, Any]], result: ImportResult
    ) -> None:
        """The bundle's schemas and fields, restrictions and defaults included.
        One already here is reported and only gains fields it lacks. Name
        templates, and a file field's `filename_template`, can name fields
        defined later (or, through a reference, on another schema), so they are
        set once every schema and field exists."""
        created: set[str] = set()
        for s in spec.sort_schemas(schemas):
            try:
                self._schemas.create(
                    s["name"],
                    description=s.get("description"),
                    parent=s.get("parent"),
                    label=s.get("label"),
                    # A bundle from before slug validation reads back as it was.
                    allow_legacy_name=True,
                )
                self._commit()
                created.add(s["name"])
            except AlreadyExistsError:
                result.schemas_existing.append(s["name"])
            for f in s.get("fields", []):
                restrictions = {
                    k: v
                    for k, v in (f.get("restrictions") or {}).items()
                    if k != "filename_template"
                }
                try:
                    self._schemas.add_field(
                        s["name"],
                        f["name"],
                        f["type"],
                        required=f.get("required", False),
                        restrictions=restrictions,
                        default_value=f.get("default_value"),
                        label=f.get("label"),
                        allow_legacy_name=True,
                        auto_name=False,  # the bundle says what the name rule is
                    )
                    self._commit()
                except AlreadyExistsError:
                    continue
                if (f.get("restrictions") or {}).get("filename_template"):
                    self._schemas.update_field(
                        s["name"], f["name"], restrictions=f["restrictions"]
                    )
                    self._commit()
        for s in schemas:
            if s["name"] in created and s.get("display_template"):
                self._schemas.update(s["name"], display_template=s["display_template"])
                self._commit()
        for s in schemas:
            if s["name"] in created and s.get("unique_keys"):
                self._schemas.set_unique_keys(s["name"], s["unique_keys"])
                self._commit()
        result.schemas_new = len(created)

    def _import_collections(
        self, collections: list[dict[str, Any]], result: ImportResult
    ) -> None:
        for c in collections:
            try:
                self._datasets.create(
                    c["name"],
                    description=c.get("description"),
                    scope=c.get("scope") or "local",
                    timezone=c.get("timezone"),
                )
                self._commit()
                result.collections_new += 1
            except AlreadyExistsError:
                result.collections_existing.append(c["name"])

    def _import_records(
        self,
        zf: zipfile.ZipFile,
        manifest: Manifest,
        result: ImportResult,
        progress: Progress | None,
    ) -> None:
        """Each record through `RecordService.add`, with its id. A record whose
        parent or referenced record is later in the bundle waits for it; one
        whose parent or target is in neither the bundle nor the project is
        skipped and named."""
        in_bundle = self._ids_in(zf)
        here: set[uuid.UUID] = set()  # written or found during this import
        waiting: dict[uuid.UUID, list[RecordLine]] = {}
        held: set[uuid.UUID] = set()
        has_files = manifest.files.included
        stored: set[str] = set()
        shapes: dict[str, dict[str, str]] = {}  # schema -> field name -> dtype
        done = 0
        pending_commit = 0
        if progress:
            progress.phase("Adding records", manifest.records)

        def dtypes(schema_name: str) -> dict[str, str]:
            if schema_name not in shapes:
                try:
                    shape = self._schemas.resolve(self._schemas.get(schema_name))
                    shapes[schema_name] = {
                        name: f.dtype for name, f in shape.by_name.items()
                    }
                except NotFoundError:
                    shapes[schema_name] = {}
            return shapes[schema_name]

        def present(record_id: uuid.UUID) -> bool:
            if record_id in here:
                return True
            if self._records.exists(str(record_id)):
                here.add(record_id)
                return True
            return False

        def blocker(line: RecordLine) -> uuid.UUID | None:
            """A record this one needs that is in the bundle but not here yet."""
            needs: list[uuid.UUID | None] = [line.parent] if line.parent else []
            kinds = dtypes(line.schema)
            for name, value in line.data.items():
                dtype = kinds.get(name)
                if dtype == "reference" and isinstance(value, str):
                    needs.append(_uuid(value))
                elif dtype == "reference_list" and isinstance(value, list):
                    needs.extend(_uuid(v) for v in value if isinstance(v, str))
            for need in needs:
                if need and need in in_bundle and not present(need):
                    return need
            return None

        def write(line: RecordLine) -> None:
            nonlocal done, pending_commit
            collection_id = None
            try:
                collection_id = str(self._datasets.id_of(line.collection))
                self._records.add(
                    line.collection,
                    line.schema,
                    line.data,
                    parent_record_id=str(line.parent) if line.parent else None,
                    with_labels=False,
                    record_id=line.id,
                    created_at=_when(line.created_at),
                    updated_at=_when(line.updated_at),
                )
            except (NotFoundError, ValidationError) as e:
                result.note(str(line.id), str(e))
                return
            here.add(line.id)
            result.records_added += 1
            pending_commit += 1
            for ref in spec.file_refs(line.data):
                self._import_file(
                    zf, ref["sha256"], has_files, stored, collection_id, result
                )
            if pending_commit >= IMPORT_BATCH:
                self._commit()
                pending_commit = 0

        def settle(line: RecordLine) -> None:
            """Write `line` unless it waits for another record; then whatever
            was waiting for it, and so on."""
            stack = [line]
            while stack:
                current = stack.pop()
                if present(current.id):
                    result.records_existing += 1
                    continue
                need = blocker(current)
                if need is not None:
                    waiting.setdefault(need, []).append(current)
                    held.add(current.id)
                    continue
                write(current)
                held.discard(current.id)
                stack.extend(waiting.pop(current.id, []))

        for line in self._lines(zf):
            settle(line)
            done += 1
            if progress:
                progress.advance(done)
        self._commit()
        for lines in waiting.values():
            for line in lines:
                if line.id in held:
                    held.discard(line.id)
                    result.note(
                        str(line.id),
                        "a record it sits inside or references was not added",
                    )

    def _import_file(
        self,
        zf: zipfile.ZipFile,
        sha: str,
        has_files: bool,
        stored: set[str],
        collection_id: str | None,
        result: ImportResult,
    ) -> None:
        """Store one file the bundle carries, once, with the collection it is
        for (so placement applies). The bytes must hash to their name."""
        if sha in stored or self._files.exists(sha):
            return
        member = spec.FILES_DIR + sha
        if not has_files or member not in zf.namelist():
            stored.add(sha)
            result.files_missing += 1
            return
        with tempfile.NamedTemporaryFile(prefix="civex-bundle-", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with zf.open(member) as src:
                shutil.copyfileobj(src, tmp, _CHUNK)
        try:
            ref = self._files.store(tmp_path, collection_id=collection_id)
            if ref.sha256 != sha:
                self._files.discard(ref.sha256)
                result.files_refused += 1
            else:
                result.files_added += 1
        finally:
            tmp_path.unlink(missing_ok=True)
        stored.add(sha)

    def _import_members(self, zf: zipfile.ZipFile, result: ImportResult) -> None:
        """Workflows and plugins, written into the project as the files they
        are. A plugin is code: the caller says so to the person."""
        if self._civex_dir is None:
            return
        for prefix, suffixes, folder, counter in (
            (spec.WORKFLOWS_DIR, spec.WORKFLOW_SUFFIXES, "workflows", "workflows"),
            (spec.PLUGINS_DIR, spec.PLUGIN_SUFFIXES, "plugins", "plugins"),
        ):
            names = [
                n[len(prefix) :]
                for n in zf.namelist()
                if n.startswith(prefix) and n != prefix
            ]
            if not names:
                continue
            target = self._civex_dir / folder
            target.mkdir(parents=True, exist_ok=True)
            for name in names:
                problem = spec.member_name_problem(name, suffixes)
                if problem:
                    result.members_skipped.append(Skipped(prefix + name, problem))
                    continue
                with zf.open(prefix + name) as src, (target / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst, _CHUNK)
                setattr(result, counter, getattr(result, counter) + 1)

    # -- reading -------------------------------------------------------------

    @staticmethod
    def _open(path: Path) -> zipfile.ZipFile:
        if not path.exists():
            raise NotFoundError(f"File not found: {path}")
        if not zipfile.is_zipfile(path):
            raise BundleError(
                f"{path.name} is not a civex bundle (a zip with a bundle.json inside)"
            )
        return zipfile.ZipFile(path)

    @staticmethod
    def _manifest(zf: zipfile.ZipFile) -> Manifest:
        try:
            raw = zf.read(spec.MANIFEST)
        except KeyError:
            raise BundleError(
                "Not a civex bundle: there is no bundle.json inside"
            ) from None
        try:
            return Manifest.from_dict(json.loads(raw))
        except json.JSONDecodeError as e:
            raise BundleError(f"bundle.json is not valid JSON: {e}") from None

    @staticmethod
    def _lines(zf: zipfile.ZipFile) -> Iterator[RecordLine]:
        with zf.open(spec.RECORDS) as f:
            for raw in f:
                text = raw.decode("utf-8").strip()
                if text:
                    yield RecordLine.parse(text)

    def _ids_in(self, zf: zipfile.ZipFile) -> set[uuid.UUID]:
        """Every record id in the bundle (a first, cheap pass), so a record
        can wait for one that comes later rather than being refused."""
        return {line.id for line in self._lines(zf)}


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
