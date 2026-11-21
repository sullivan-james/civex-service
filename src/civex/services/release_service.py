"""Releases: frozen, citable copies of the data (`civex.domain.release`).

One rule for `civex release ...`, `/releases` and the app.

**Files are referenced, never copied.** Making a release writes a small
bundle of its records with `BundleService.export` (no files), hashes it (the
hash covers every cited file by its sha256, so no file is read), adds
`release.json` and `CITATION.cff`, and keeps it in the object store. The
release then *owns* every file its records cite, and its bundle, through
`file_references.release_id`: one INSERT ... SELECT from the records' own
rows, each pointing at the copy its records point at. So garbage collection
keeps them, "used by" names the release, file moves carry its pointers with
its records' (`domain.placement.moving`), and making a release asks no drive
for anything: the only bytes written are the bundle's.

A release's content never changes. Its citation metadata may be corrected and
it may be withdrawn with a reason (both keep everything), or **yanked**: its
data is given up (it owns nothing any more, and clean-up then removes what
nothing else uses), leaving a tombstone that still answers a citation. Each is
a history entry. Making, correcting, withdrawing and yanking need
`change_structure`.

**Getting the data out** goes through `FileAccessService` reading the
release's frozen records (`release_records.FrozenRecords`): the same path
rule, plan (what is out of reach, by drive), folder of links or copies on a
drive, move onto one drive and (under the zip limit) zip as a live selection.
A folder gets a BagIt-style `manifest-sha256.txt`.

Restoring a release is reading its bundle into a new project with
`civex bundle import` (or `POST /bundle/import`): there is no other path.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from civex import __version__
from civex.domain import permissions
from civex.domain import release as rules
from civex.domain.bundle import EXTENSION, ExportOptions
from civex.domain.dtos import ReleaseDTO
from civex.domain.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    ValidationError,
)
from civex.domain.file_access import FilePlan, FileSelection
from civex.domain.permissions import EVERYTHING, Permissions
from civex.domain.query import RecordQuery
from civex.domain.transfers import KIND_FILES, MAX_TRANSFER_FILES, TransferSpec
from civex.repositories.protocols import (
    AuditRepository,
    FileReferenceRepository,
    ObjectStore,
    ReleaseRepository,
)
from civex.services.bundle_service import BundleService
from civex.services.progress import Progress

# The RecordQuery fields a release's scope may hold (`sort` is not a scope).
_QUERY_FIELDS = (
    "dataset",
    "schema",
    "within",
    "parent_record_id",
    "filter_tree",
    "where",
    "search",
    "search_fields",
)
# What a folder of a release's files carries beside them.
BAG_MANIFEST = "manifest-sha256.txt"


@dataclass
class ReleaseScope:
    """What a release covers: the whole project (none set), these collections
    (by name), the records a query lists, or exactly these records (by id);
    with the records above them, so it reads in whole."""

    collections: list[str] | None = None
    query: RecordQuery | None = None
    records: list[str] | None = None

    def __post_init__(self) -> None:
        if self.collections is not None and not self.collections:
            self.collections = None
        if self.records is not None and not self.records:
            raise ValidationError("Choose at least one record to release")
        chosen = (self.collections, self.query, self.records)
        if sum(x is not None for x in chosen) > 1:
            raise ValidationError(
                "A release covers some collections, a query's records or some "
                "records: one of them"
            )

    def to_dict(self) -> dict[str, Any]:
        if self.collections:
            return {"collections": list(self.collections)}
        if self.records:
            return {"records": list(self.records)}
        if self.query is not None:
            return {
                "query": {
                    k: v
                    for k in _QUERY_FIELDS
                    if (v := getattr(self.query, k)) not in (None, [], "")
                }
            }
        return {}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ReleaseScope":
        raw = raw or {}
        if raw.get("collections"):
            return cls(collections=[str(c) for c in raw["collections"]])
        if raw.get("records"):
            return cls(records=[str(r) for r in raw["records"]])
        if isinstance(raw.get("query"), dict):
            q = {k: v for k, v in raw["query"].items() if k in _QUERY_FIELDS}
            return cls(query=RecordQuery(**q))
        return cls()

    def options(self, include_workflows: bool) -> ExportOptions:
        return ExportOptions(
            include_records=True,
            include_files=False,
            include_workflows=include_workflows,
            collections=self.collections,
            query=self.query,
            record_ids=self.records,
        )


@dataclass
class ReleasePlan:
    """What a release of a scope would hold, from the catalog (no drive is
    asked): records per collection, the files they cite by the drive each
    record's copy is on (informational: a release needs no drive to be made),
    and the history position it would be taken at."""

    records: int = 0
    collections: dict[str, int] = field(default_factory=dict)
    schemas: int = 0
    files: int = 0
    file_bytes: int = 0
    by_drive: list[dict[str, Any]] = field(default_factory=list)
    workflows: int = 0
    plugins: int = 0
    feed_seq: int | None = None
    local_seq: int = 0
    unsent: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class VerifyResult:
    """Whether a release still holds what it was made with: its records'
    hash, and whether every file it cites is recorded here (and, deep, that
    each copy's bytes still hash to its name)."""

    name: str
    matches: bool
    expected: str
    actual: str | None
    # The bundle's own bytes match the hash it is kept under.
    bundle_intact: bool
    files: int = 0
    # Cited files with no copy recorded on this computer.
    files_not_here: int = 0
    # Cited files whose copies here were never read back against their hash.
    files_unchecked: int = 0
    # Deep only: files read back, and those whose bytes didn't match.
    files_read: int = 0
    files_bad: list[str] = field(default_factory=list)
    deep: bool = False
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class YankPlan:
    """What yanking a release gives up: how many of its files (and bytes) are
    used by nothing else, so clean-up would remove them (counted by the
    clean-up's own rule, `copies_in_use`), and how many stay for their other
    users."""

    name: str
    files: int = 0
    unused_files: int = 0
    unused_bytes: int = 0
    kept_files: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class CollectionChanges:
    collection_id: str | None
    collection: str | None  # None: deleted for good, or a deleted collection
    added: int = 0
    changed: int = 0
    deleted: int = 0
    in_scope: bool = True

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ChangesSince:
    """What changed in the project after a release was made."""

    name: str
    comparable: bool
    # How the position was compared: "feed" (the authority's numbers) or
    # "local" (this copy's own order); None when it can't be.
    by: str | None
    reason: str | None = None
    added: int = 0
    changed: int = 0
    deleted: int = 0
    collections: list[CollectionChanges] = field(default_factory=list)
    # Entries about other kinds (schema, field, dataset, view...) since.
    structure: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = dataclasses.asdict(self)
        out["collections"] = [c.to_dict() for c in self.collections]
        return out


class _Undo(Exception):
    """Rolls back the savepoint a yank's plan is counted in."""


Locate = Callable[[dict[str, str | None]], Callable[[str], dict[str, Any]]]


class ReleaseService:
    def __init__(
        self,
        repo: ReleaseRepository,
        bundles: BundleService,
        store: ObjectStore,
        audit_repo: AuditRepository | None = None,
        permissions: Permissions = EVERYTHING,
        actor: str | None = None,
        collections: Callable[[], dict[uuid.UUID, str]] | None = None,
        refs: FileReferenceRepository | None = None,
    ) -> None:
        self._repo = repo
        self._bundles = bundles
        self._store = store
        self._audit = audit_repo
        self._permissions = permissions
        self._actor = actor
        self._refs = refs
        # Live collections by id, for naming what changed since.
        self._collections = collections or (lambda: {})
        # Where history is on the authority, and how many changes here it
        # hasn't got: (feed number or None, unsent). Injected from sync.
        self.position: Callable[[], tuple[int | None, int]] = lambda: (None, 0)
        # Fetch a file from the authority (a bundle made on another copy).
        self.fetch: Callable[[str], bool] | None = None
        # Whether this copy keeps everyone's files (it serves devices, or
        # syncs with nobody): only then does a release made elsewhere own the
        # files it cites here. A device owns only the bundle; the authority
        # keeps the files. Injected from sync.
        self.keeps_files: Callable[[], bool] = lambda: True
        # FileAccessService, to lay a release's files out; and where a file is
        # for an owner that isn't a record (`RecordService.locate_pointed`).
        self.files: Any = None
        self.locate: Locate | None = None
        # A SAVEPOINT (`AppContext.all_or_nothing`), to count a yank's effect
        # by doing it and taking it back.
        self.savepoint: Callable[[], Any] | None = None
        # Read back exactly these files' copies (`ObjectStore.verify`).
        self.read_back: Callable[..., list[str]] | None = None

    # -- reading ---------------------------------------------------------------

    def list_all(self) -> list[ReleaseDTO]:
        self._permissions.require(permissions.READ)
        return self._repo.list_all()

    def get(self, name: str) -> ReleaseDTO:
        """A release by its name, its id, or the start of its id."""
        self._permissions.require(permissions.READ)
        found = self._repo.get_by_name(name) or self._repo.get_by_prefix(name)
        if found is None:
            raise NotFoundError(f"Release '{name}' not found")
        return found

    def plan(
        self, scope: ReleaseScope | None = None, include_workflows: bool = True
    ) -> ReleasePlan:
        """What a release of `scope` would hold (the bundle's own walk, so the
        count can't disagree with the release), from the catalog."""
        self._permissions.require(permissions.READ)
        scope = scope or ReleaseScope()
        counted = self._bundles.plan_export(scope.options(include_workflows))
        collections, ids = self._owners(scope)
        names = self._collections()
        per = self._repo.records_per_collection(collections, ids)
        feed, unsent = self.position()
        return ReleasePlan(
            records=counted.records,
            collections={
                names.get(cid, str(cid)): n for cid, n in sorted(per.items(), key=str)
            },
            schemas=counted.schemas,
            files=counted.files,
            file_bytes=counted.file_bytes,
            by_drive=[
                {"volume": v, "files": n, "bytes": b}
                for v, n, b in self._repo.cited_by_drive(collections, ids)
            ],
            workflows=counted.workflows,
            plugins=counted.plugins,
            feed_seq=feed,
            local_seq=self._repo.history_position(),
            unsent=unsent,
        )

    def cite(self, name: str, form: str = "text") -> str:
        """How to cite a release: `text`, `bibtex` or `cff`."""
        return rules.citation(self.facts(self.get(name)), form)

    @staticmethod
    def facts(r: ReleaseDTO) -> rules.CitationFacts:
        return rules.CitationFacts(
            name=r.name,
            title=r.title,
            authors=[dict(a) for a in r.authors],
            year=str(r.created_at.year),
            date=r.created_at.date().isoformat(),
            content_hash=r.content_hash,
            licence=r.licence,
            doi=r.doi,
            description=r.description,
            keywords=list(r.keywords),
        )

    @staticmethod
    def preview(values: dict[str, Any], name: str, form: str = "text") -> str:
        """How a release with these words would be cited, before it is made
        (its content hash isn't known yet, so it shows as `sha256:…`)."""
        given = {k: values.get(k) for k in rules.METADATA_FIELDS if k in values}
        meta = rules.check_metadata(
            {**given, "title": values.get("title") or "Untitled"}
        )
        now = datetime.now(timezone.utc)
        return rules.citation(
            rules.CitationFacts(
                name=name or "v1",
                title=meta["title"],
                authors=meta.get("authors", []),
                year=str(now.year),
                date=now.date().isoformat(),
                content_hash=rules.HASH_PREFIX + "…",
                licence=meta.get("licence"),
                doi=meta.get("doi"),
                description=meta.get("description"),
                keywords=meta.get("keywords", []),
            ),
            form,
        )

    # -- making ----------------------------------------------------------------

    def create(
        self,
        name: str,
        title: str,
        scope: ReleaseScope | None = None,
        description: str | None = None,
        authors: list[Any] | None = None,
        licence: str | None = None,
        doi: str | None = None,
        keywords: list[str] | None = None,
        include_workflows: bool = True,
        progress: Progress | None = None,
    ) -> ReleaseDTO:
        """Freeze `scope` as a release named `name`: write the bundle of its
        records, hash it, keep it in the object store, record the manifest and
        own the files the records cite. No drive is asked for a file."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        name = rules.check_name(name)
        meta = rules.check_metadata(
            {
                "title": title,
                "description": description,
                "authors": authors or [],
                "licence": licence,
                "doi": doi,
                "keywords": keywords or [],
            }
        )
        if self._repo.get_by_name(name) is not None:
            raise AlreadyExistsError(f"A release named '{name}' already exists")
        scope = scope or ReleaseScope()
        feed_seq, unsent = self.position()
        if unsent:
            raise ValidationError(
                f"This computer has {unsent} change{'s' if unsent != 1 else ''} "
                "the server hasn't got yet: sync first, so the release is taken "
                "at a point every copy of the project shares"
            )
        collections, _ = self._owners(scope, walk=False)
        local_seq = self._repo.history_position()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with tempfile.TemporaryDirectory(prefix="civex-release-") as tmp:
            path = Path(tmp) / self.file_name_for(name)
            plan = self._bundles.export(
                path, scope.options(include_workflows), progress
            )
            written = self._bundles.written_ids
            with zipfile.ZipFile(path) as zf:
                hashed = rules.hash_bundle(zf)
            counts = {
                "schemas": plan.schemas,
                "collections": list(plan.collections),
                "records": plan.records,
                "files": len(hashed.cited),
                "file_bytes": plan.file_bytes,
                "workflows": plan.workflows,
                "plugins": plan.plugins,
            }
            draft = ReleaseDTO(
                id=uuid.uuid4(),
                name=name,
                title=meta["title"],
                description=meta.get("description"),
                authors=meta.get("authors", []),
                licence=meta.get("licence"),
                doi=meta.get("doi"),
                keywords=meta.get("keywords", []),
                scope=scope.to_dict(),
                content_hash=hashed.content_hash,
                bundle_sha256="",
                bundle_size=0,
                counts=counts,
                local_seq=local_seq,
                feed_seq=feed_seq,
                civex_version=__version__,
                created_at=now,
                created_by=self._actor,
            )
            with zipfile.ZipFile(path, "a") as zf:
                zf.writestr(rules.RELEASE_JSON, json.dumps(_manifest(draft), indent=1))
                zf.writestr(rules.CITATION_CFF, rules.citation_cff(self.facts(draft)))
            ref = self._store.put_path(path, original_filename=path.name)
        made = self._repo.create(
            **{
                k: v
                for k, v in dataclasses.asdict(draft).items()
                if k not in ("bundle_sha256", "bundle_size")
            }
            | {"bundle_sha256": ref.sha256, "bundle_size": ref.size}
        )
        ids = list(written) if written is not None else None
        self._repo.own_cited(made.id, collections if ids is None else None, ids)
        self._repo.own(made.id, [ref.sha256])
        if self._repo.owned(made.id) < len(set(hashed.cited) | {ref.sha256}):
            # The catalog has drifted from the records (`civex store
            # rebuild-refs` mends it): own what the records say, by content.
            self._repo.own(made.id, hashed.cited)
        self._log("create", None, made)
        return made

    @staticmethod
    def file_name_for(name: str) -> str:
        return f"release-{name}{EXTENSION}"

    # -- after it is made ------------------------------------------------------

    def correct(self, name: str, **values: Any) -> ReleaseDTO:
        """Correct a release's citation metadata (title, description, authors,
        licence, DOI, keywords). Its content never changes; the correction is
        in history."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        release = self.get(name)
        self._not_yanked(release)
        unknown = set(values) - set(rules.METADATA_FIELDS)
        if unknown:
            raise ValidationError(
                f"Only a release's {', '.join(rules.METADATA_FIELDS)} can be "
                f"corrected, not {', '.join(sorted(unknown))}"
            )
        changes = {
            k: v
            for k, v in rules.check_metadata(values).items()
            if getattr(release, k) != v
        }
        if not changes:
            return release
        after = self._repo.update(
            release.id, **changes, updated_at=datetime.now(timezone.utc)
        )
        self._log("update", release, after)
        return after

    def withdraw(self, name: str, reason: str) -> ReleaseDTO:
        """Mark a release withdrawn, saying why. It keeps its data (a paper
        that cited it can still be checked), and it says it was withdrawn
        wherever it is shown. To give the data up, yank it."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        release = self.get(name)
        text = _reason(reason, "withdrawn")
        if release.withdrawn_at is not None:
            raise ValidationError(f"Release '{release.name}' is already withdrawn")
        now = datetime.now(timezone.utc)
        after = self._repo.update(
            release.id,
            withdrawn_at=now,
            withdrawn_by=self._actor,
            withdrawn_reason=text,
            updated_at=now,
        )
        self._log("update", release, after)
        return after

    def plan_yank(self, name: str) -> YankPlan:
        """What yanking would give up, counted by the clean-up's own rule
        (`copies_in_use`) on the release's copies before and after it stops
        owning them, inside a savepoint that is then rolled back. From the
        catalog: no drive is read."""
        release = self.get(name)
        plan = YankPlan(release.name)
        if release.yanked_at is not None or self._refs is None:
            return plan
        if self.savepoint is None:
            raise ValidationError("Yanking needs the project's database")
        refs = self._refs
        try:
            with self.savepoint():
                pages: list[list[str]] = []
                after = ""
                while page := self._repo.owned_shas(release.id, after):
                    pages.append(page)
                    after = page[-1]
                copies: dict[str, list[tuple[str, int]]] = {}
                before: set[tuple[str, str]] = set()
                for page in pages:
                    found = self._store.copies(page)
                    copies.update(found)
                    before |= refs.copies_in_use(
                        (sha, v) for sha, rows in found.items() for v, _ in rows
                    )
                self._repo.disown(release.id)
                for page in pages:
                    now = refs.copies_in_use(
                        (sha, v) for sha in page for v, _ in copies.get(sha, [])
                    )
                    for sha in page:
                        plan.files += 1
                        used = [
                            (v, size)
                            for v, size in copies.get(sha, [])
                            if (sha, v) in before
                        ]
                        freed = [size for v, size in used if (sha, v) not in now]
                        plan.unused_bytes += sum(freed)
                        if used and len(freed) == len(used):
                            plan.unused_files += 1
                        else:
                            plan.kept_files += 1
                raise _Undo()
        except _Undo:
            pass
        return plan

    def yank(self, name: str, reason: str) -> ReleaseDTO:
        """Give a release's data up for good: it stops owning its files and
        its bundle, so clean-up removes whatever nothing else uses. What stays
        is a tombstone (name, hash, title, citation, who yanked it, when and
        why) so a citation still finds it. It is withdrawn too. Can't be
        undone."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        release = self.get(name)
        self._not_yanked(release)
        text = _reason(reason, "yanked")
        now = datetime.now(timezone.utc)
        self._repo.disown(release.id)
        after = self._repo.update(
            release.id,
            yanked_at=now,
            yanked_by=self._actor,
            yanked_reason=text,
            withdrawn_at=release.withdrawn_at or now,
            withdrawn_by=release.withdrawn_by or self._actor,
            withdrawn_reason=release.withdrawn_reason or text,
            updated_at=now,
        )
        self._log("update", release, after)
        return after

    def verify(
        self, name: str, deep: bool = False, progress: Progress | None = None
    ) -> VerifyResult:
        """Whether the release still holds what it was made with: its bundle
        read back and its content hash recomputed (no file is read: the hash
        covers files by their sha256), and every file it cites recorded in
        the inventory here. `deep` also reads every cited file here back
        against its hash (`ObjectStore.verify` over exactly them): a long job
        for a large release, reported through `progress`."""
        release = self.get(name)
        if release.yanked_at is not None:
            return VerifyResult(
                release.name,
                False,
                release.content_hash,
                None,
                False,
                problems=[
                    f"It was yanked on {release.yanked_at.date().isoformat()}: "
                    "its data has been given up"
                ],
            )
        try:
            with self._bundle(release) as f:
                digest = hashlib.sha256()
                while chunk := f.read(1024 * 1024):
                    digest.update(chunk)
                intact = digest.hexdigest() == release.bundle_sha256
                f.seek(0)
                with zipfile.ZipFile(f) as zf:
                    hashed = rules.hash_bundle(zf)
        except (FileNotFoundError, zipfile.BadZipFile) as e:
            return VerifyResult(
                release.name,
                False,
                release.content_hash,
                None,
                False,
                problems=[_unreadable(e)],
            )
        out = VerifyResult(
            release.name,
            False,
            release.content_hash,
            hashed.content_hash,
            intact,
            files=len(hashed.cited),
            deep=deep,
            problems=list(hashed.problems),
        )
        if not intact:
            out.problems.append(
                "The bundle's bytes do not match the hash it is kept under"
            )
        if hashed.content_hash != release.content_hash:
            out.problems.append("Its contents hash differently from when it was made")
        missing, unchecked = self._repo.inventory_state(hashed.cited)
        out.files_not_here = len(missing)
        out.files_unchecked = len(unchecked)
        if missing:
            if not self.keeps_files():
                out.notes.append(
                    f"{len(missing)} of its files are not on this computer: the "
                    "server keeps them"
                )
            else:
                out.problems.append(
                    f"{len(missing)} of its files are recorded on no drive here"
                )
        if deep and self.read_back is not None:
            here = [s for s in hashed.cited if s not in missing]
            if progress:
                progress.phase(f"Reading back {len(here)} files", len(here))
            out.files_bad = self.read_back(here, progress.advance if progress else None)
            out.files_read = len(here)
            out.files_unchecked = 0
            if out.files_bad:
                out.problems.append(
                    f"{len(out.files_bad)} of its files no longer match their hash "
                    "(the bad copies were removed)"
                )
        out.matches = not out.problems
        return out

    @contextmanager
    def open_bundle(self, name: str) -> Iterator[tuple[ReleaseDTO, Any]]:
        """The release and its bundle's bytes to read (fetched from the server
        first when this copy hasn't got them)."""
        release = self.get(name)
        self._not_yanked(release)
        with self._bundle(release) as f:
            yield release, f

    def bundle_here(self, name: str) -> tuple[ReleaseDTO, bool]:
        """The release, and whether its bundle is on this computer (fetched
        from the server first when it isn't)."""
        release = self.get(name)
        if release.yanked_at is not None:
            return release, False
        if not self._store.exists(release.bundle_sha256) and self.fetch is not None:
            try:
                self.fetch(release.bundle_sha256)
            except Exception:  # the server can't be reached
                pass
        return release, self._store.exists(release.bundle_sha256)

    # -- getting the data out --------------------------------------------------

    @contextmanager
    def file_access(self, name: str) -> Iterator[tuple[Any, FileSelection]]:
        """`FileAccessService` reading this release's frozen records, and the
        selection of all of them: plan, export, gather or zip with it exactly
        as with a live selection."""
        from civex.services.release_records import FrozenRecords

        if self.files is None or self.locate is None:
            raise ValidationError("Files can't be laid out here")
        release = self.get(name)
        self._not_yanked(release)
        pointers = self._repo.owned_pointers(release.id)
        locate = self.locate

        def where(cited: set[str]) -> Callable[[str], dict[str, Any]]:
            # On a device the release owns only its bundle: its files are
            # found by content, where the records here have them.
            return locate({sha: pointers.get(sha) for sha in cited})

        with self._bundle(release) as f:
            records = FrozenRecords(f, where)
        yield self.files.with_records(records), FileSelection(record_ids=records.ids)

    def file_plan(self, name: str, progress: Progress | None = None) -> FilePlan:
        """Every file the release cites, each at its path in the record
        hierarchy, and whether it can be reached now (grouped by drive)."""
        with self.file_access(name) as (access, selection):
            return access.plan(selection, progress=progress)

    def write_bag(
        self, name: str, dest: Path, plan: FilePlan
    ) -> list[tuple[str, Path]]:
        """Add to a folder of a release's files what makes it stand alone:
        `manifest-sha256.txt` (BagIt: each file's sha256 and its path), the
        release's `release.json` and `CITATION.cff`. Returns (name, file) for
        each, to put beside the files in a zip."""
        release = self.get(name)
        lines = sorted(f"{i.sha256}  {i.path}" for i in plan.items if i.available)
        written = {
            BAG_MANIFEST: "\n".join(lines) + "\n",
            rules.RELEASE_JSON: json.dumps(_manifest(release), indent=1),
            rules.CITATION_CFF: rules.citation_cff(self.facts(release)),
        }
        out = []
        for member, text in written.items():
            (dest / member).write_text(text, encoding="utf-8")
            out.append((member, dest / member))
        return out

    def gather_spec(self, name: str, volume: str) -> TransferSpec:
        """The move that puts this release's copies of its files on `volume`:
        only its own pointers move (its records' stay), so a copy records use
        elsewhere is copied there, not moved."""
        release = self.get(name)
        self._not_yanked(release)
        shas = [
            s
            for s in self._repo.owned_pointers(release.id)
            if s != release.bundle_sha256
        ]
        if len(shas) > MAX_TRANSFER_FILES:
            raise ValidationError(
                f"A release of {len(shas)} files is moved a collection at a time "
                f"(at most {MAX_TRANSFER_FILES} files in one move)"
            )
        return TransferSpec(
            kind=KIND_FILES,
            targets=[volume],
            shas=shas,
            release_ids=[str(release.id)],
            freeze_sources=False,
        )

    def changes_since(self, name: str) -> ChangesSince:
        """How many records were added, changed and deleted (per collection)
        after the release was made, from history: by the authority's numbers
        on a synced project, else this copy's own order. Two queries."""
        release = self.get(name)
        feed, _ = self.position()
        if release.feed_seq is not None and feed is not None:
            by = "feed"
        elif release.local_seq is not None:
            by = "local"
        else:
            return ChangesSince(
                release.name,
                False,
                None,
                "It was made on another computer before the project synced, so "
                "its place in history isn't known here",
            )
        rows, others = self._repo.changes_since(
            release.local_seq if by == "local" else None,
            release.feed_seq if by == "feed" else None,
            release.id,
        )
        names = self._collections()
        in_scope = set(release.scope.get("collections") or [])
        out = ChangesSince(release.name, True, by)
        for cid, added, changed, deleted in rows:
            if not (added or changed or deleted):
                continue
            label = names.get(cid) if cid else None
            out.collections.append(
                CollectionChanges(
                    str(cid) if cid else None,
                    label,
                    added,
                    changed,
                    deleted,
                    in_scope=not in_scope or label in in_scope,
                )
            )
            out.added += added
            out.changed += changed
            out.deleted += deleted
        out.collections.sort(key=lambda c: (c.collection is None, c.collection or ""))
        out.structure = {k: v for k, v in others.items() if k != "release"}
        return out

    def kept_for(self, record_ids: list[uuid.UUID]) -> dict[str, int]:
        """Of the files these records cite, how many each release keeps (by
        name): what a permanent delete of them leaves on the drives, and
        which release to yank to give it up."""
        if self._refs is None:
            return {}
        return self._refs.releases_keeping(record_ids)

    # -- for sync --------------------------------------------------------------

    def check_incoming(
        self, state: dict[str, Any], head: dict[str, Any] | None
    ) -> None:
        """A release another device sent: its words must be ones a person's
        could have, its name free, once made its content can't change, and a
        yank can't be taken back."""
        rules.check_name(state.get("name"))
        rules.check_metadata({k: state.get(k) for k in rules.METADATA_FIELDS})
        if not state.get("content_hash") or not state.get("bundle_sha256"):
            raise ValidationError("A release names its content hash and bundle")
        if head is None:
            taken = self._repo.get_by_name(str(state["name"]))
            if taken is not None and str(taken.id) != str(state.get("id")):
                raise ValidationError(
                    f"A release named '{state['name']}' already exists"
                )
            return
        changed = sorted(
            k for k in rules.CONTENT_FIELDS if k in head and head.get(k) != state.get(k)
        )
        if changed:
            raise ValidationError(
                f"A release's content never changes once made ({', '.join(changed)})"
            )
        if head.get("yanked_at") and not state.get("yanked_at"):
            raise ValidationError("A yanked release can't be brought back")

    def index_waiting(self, bundle_sha256: str | None = None) -> int:
        """Own the files releases made elsewhere cite, once their bundle is
        here (read for its records; no file is read), on a copy that keeps
        everyone's files. Called when a file arrives at the authority. Returns
        how many releases were indexed."""
        if not self.keeps_files():
            return 0
        done = 0
        for release in self._repo.waiting_index(bundle_sha256):
            if not self._store.exists(release.bundle_sha256):
                continue
            with self._store.open(release.bundle_sha256) as f:
                with zipfile.ZipFile(f) as zf:
                    cited = rules.hash_bundle(zf).cited
            self._repo.own(release.id, [release.bundle_sha256, *cited])
            self._repo.mark_indexed(release.id)
            done += 1
        return done

    # -- helpers ---------------------------------------------------------------

    def _owners(
        self, scope: ReleaseScope, walk: bool = True
    ) -> tuple[list[uuid.UUID] | None, list[uuid.UUID] | None]:
        """The scope as the catalog asks it: collection ids (None: all), or
        (with `walk`) the record ids a query or a pick takes."""
        if scope.collections:
            names = {n: cid for cid, n in self._collections().items()}
            missing = [n for n in scope.collections if n not in names]
            if missing:
                raise NotFoundError(f"Collection '{missing[0]}' not found")
            return [names[n] for n in scope.collections], None
        if walk and (scope.query is not None or scope.records is not None):
            self._bundles.plan_export(scope.options(False))
            return None, list(self._bundles.written_ids or [])
        return None, None

    @staticmethod
    def _not_yanked(release: ReleaseDTO) -> None:
        if release.yanked_at is not None:
            raise ValidationError(
                f"Release '{release.name}' was yanked on "
                f"{release.yanked_at.date().isoformat()}: its data has been given up"
            )

    @contextmanager
    def _bundle(self, release: ReleaseDTO) -> Iterator[Any]:
        sha = release.bundle_sha256
        if not self._store.exists(sha) and self.fetch is not None:
            try:
                self.fetch(sha)
            except Exception:  # the server can't be reached: say it isn't here
                pass
        with self._store.open(sha) as f:
            yield f

    def _log(self, action: str, before: ReleaseDTO | None, after: ReleaseDTO) -> None:
        if self._audit is not None:
            self._audit.log_change(
                action,
                "release",
                after.id,
                before.to_dict() if before else None,
                after.to_dict(),
            )


def _manifest(r: ReleaseDTO) -> dict[str, Any]:
    out = {
        k: v
        for k, v in r.to_dict().items()
        if k not in ("bundle_sha256", "bundle_size", "local_seq")
        and not k.startswith(("withdrawn_", "yanked_"))
    }
    out["hash_definition"] = f"civex-release-content/{rules.HASH_VERSION}"
    return out


def _reason(reason: str | None, what: str) -> str:
    text = (reason or "").strip()
    if not text:
        raise ValidationError(f"Say why the release is {what}")
    return text


def _unreadable(e: Exception) -> str:
    if isinstance(e, FileNotFoundError):
        return (
            "The bundle is not on this computer, and the server hasn't got it "
            "either (or can't be reached)"
        )
    return "The bundle is not a readable zip"
