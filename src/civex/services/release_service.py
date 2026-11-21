"""Releases: frozen, citable copies of the data (`civex.domain.release`).

One rule for `civex release ...`, `/releases` and the app. Making a release
writes a bundle with `BundleService.export` (the one exporter: a release is a
bundle with a name and a manifest), hashes its contents, adds `release.json`
and `CITATION.cff` to it, and keeps it in the object store under the zip's
own sha256, so drive placement, a bucket and sync's file movement all apply
to it as to any file (GC keeps it while the release exists). The release
row carries the manifest and syncs as kind `release`; the bundle follows as
a file, fetched from the authority when a copy that hasn't got it asks for
it (verify, download).

A release is never deleted and its content never changes. Its citation
metadata (title, description, authors, licence, DOI) may be corrected and it
may be withdrawn with a reason: each is a history entry, so what it said
before stays on record. Making, correcting and withdrawing need
`change_structure`: a release is a project-level thing others depend on, as
a kind of record is.

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
from civex.domain.permissions import EVERYTHING, Permissions
from civex.domain.query import RecordQuery
from civex.repositories.protocols import (
    AuditRepository,
    ObjectStore,
    ReleaseRepository,
)
from civex.services.bundle_service import BundlePlan, BundleService
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


@dataclass
class ReleaseScope:
    """What a release covers: the whole project (neither set), these
    collections, or the records a query lists (and the records above them)."""

    collections: list[str] | None = None
    query: RecordQuery | None = None

    def __post_init__(self) -> None:
        if self.collections is not None and self.query is not None:
            raise ValidationError(
                "A release covers some collections or a query's records, not both"
            )
        if self.collections is not None and not self.collections:
            self.collections = None

    def to_dict(self) -> dict[str, Any]:
        if self.collections:
            return {"collections": list(self.collections)}
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
        if isinstance(raw.get("query"), dict):
            q = {k: v for k, v in raw["query"].items() if k in _QUERY_FIELDS}
            return cls(query=RecordQuery(**q))
        return cls()

    def options(self, include_files: bool, include_workflows: bool) -> ExportOptions:
        return ExportOptions(
            include_records=True,
            include_files=include_files,
            include_workflows=include_workflows,
            collections=self.collections,
            query=self.query,
        )


@dataclass
class VerifyResult:
    """Whether a release's stored bundle still holds what it was made with."""

    name: str
    matches: bool
    expected: str
    actual: str | None
    # The bundle's own bytes match the hash it is stored under.
    bundle_intact: bool
    problems: list[str] = field(default_factory=list)

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
    ) -> None:
        self._repo = repo
        self._bundles = bundles
        self._store = store
        self._audit = audit_repo
        self._permissions = permissions
        self._actor = actor
        # Live collections by id, for naming what changed since.
        self._collections = collections or (lambda: {})
        # Where history is on the authority, and how many changes here it
        # hasn't got: (feed number or None, unsent). Injected from sync.
        self.position: Callable[[], tuple[int | None, int]] = lambda: (None, 0)
        # Fetch a file from the authority (a bundle made on another copy).
        self.fetch: Callable[[str], bool] | None = None

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
        self,
        scope: ReleaseScope | None = None,
        include_files: bool = True,
        include_workflows: bool = True,
    ) -> BundlePlan:
        """What a release of `scope` would hold: the bundle's own plan."""
        self._permissions.require(permissions.READ)
        scope = scope or ReleaseScope()
        return self._bundles.plan_export(
            scope.options(include_files, include_workflows)
        )

    def cite(self, name: str, form: str = "text") -> str:
        """How to cite a release: `text`, `bibtex` or `cff`."""
        return rules.citation(self.facts(self.get(name)), form)

    @staticmethod
    def facts(r: ReleaseDTO) -> rules.CitationFacts:
        return rules.CitationFacts(
            name=r.name,
            title=r.title,
            authors=list(r.authors),
            year=str(r.created_at.year),
            date=r.created_at.date().isoformat(),
            content_hash=r.content_hash,
            licence=r.licence,
            doi=r.doi,
            description=r.description,
        )

    # -- making ----------------------------------------------------------------

    def create(
        self,
        name: str,
        title: str,
        scope: ReleaseScope | None = None,
        description: str | None = None,
        authors: list[str] | None = None,
        licence: str | None = None,
        doi: str | None = None,
        include_files: bool = True,
        include_workflows: bool = True,
        progress: Progress | None = None,
    ) -> ReleaseDTO:
        """Freeze `scope` as a release named `name`: write its bundle, hash it,
        keep it in the object store and record the manifest."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        name = rules.check_name(name)
        meta = rules.check_metadata(
            {
                "title": title,
                "description": description,
                "authors": authors or [],
                "licence": licence,
                "doi": doi,
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
        local_seq = self._repo.history_position()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with tempfile.TemporaryDirectory(prefix="civex-release-") as tmp:
            path = Path(tmp) / self.file_name_for(name)
            plan = self._bundles.export(
                path, scope.options(include_files, include_workflows), progress
            )
            with zipfile.ZipFile(path) as zf:
                hashed = rules.hash_bundle(zf, check_files=False)
            counts = {
                **plan.to_dict(),
                "files_carried": hashed.files,
            }
            counts.pop("include_files", None)
            release_id = uuid.uuid4()
            draft = ReleaseDTO(
                id=release_id,
                name=name,
                title=meta["title"],
                description=meta.get("description"),
                authors=meta.get("authors", []),
                licence=meta.get("licence"),
                doi=meta.get("doi"),
                scope=scope.to_dict(),
                include_files=include_files,
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
                manifest = {
                    k: v
                    for k, v in draft.to_dict().items()
                    if k not in ("bundle_sha256", "bundle_size")
                }
                manifest["hash_definition"] = (
                    f"civex-release-content/{rules.HASH_VERSION}"
                )
                zf.writestr(rules.RELEASE_JSON, json.dumps(manifest, indent=1))
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
        self._log("create", None, made)
        return made

    @staticmethod
    def file_name_for(name: str) -> str:
        return f"release-{name}{EXTENSION}"

    # -- after it is made ------------------------------------------------------

    def correct(self, name: str, **values: Any) -> ReleaseDTO:
        """Correct a release's citation metadata (title, description, authors,
        licence, DOI). Its content never changes; the correction is in history."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        release = self.get(name)
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
        """Mark a release withdrawn, saying why. It and its bundle are kept (a
        paper that cited it can still be checked), and it says it was
        withdrawn wherever it is shown."""
        self._permissions.require(permissions.CHANGE_STRUCTURE)
        release = self.get(name)
        text = (reason or "").strip()
        if not text:
            raise ValidationError("Say why the release is withdrawn")
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

    def verify(self, name: str) -> VerifyResult:
        """Read the stored bundle back and recompute its content hash (checking
        every carried file against its own hash too): whether it still holds
        exactly what the release was made with."""
        release = self.get(name)
        problems: list[str] = []
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
                [_unreadable(e)],
            )
        problems += hashed.problems
        if not intact:
            problems.append("The bundle's bytes do not match the hash it is kept under")
        matches = hashed.content_hash == release.content_hash and not problems
        if hashed.content_hash != release.content_hash:
            problems.append("Its contents hash differently from when it was made")
        return VerifyResult(
            release.name,
            matches,
            release.content_hash,
            hashed.content_hash,
            intact,
            problems,
        )

    @contextmanager
    def open_bundle(self, name: str) -> Iterator[tuple[ReleaseDTO, Any]]:
        """The release and its bundle's bytes to read (fetched from the server
        first when this copy hasn't got them)."""
        release = self.get(name)
        with self._bundle(release) as f:
            yield release, f

    def bundle_here(self, name: str) -> tuple[ReleaseDTO, bool]:
        """The release, and whether its bundle is on this computer (fetched
        from the server first when it isn't)."""
        release = self.get(name)
        if not self._store.exists(release.bundle_sha256) and self.fetch is not None:
            try:
                self.fetch(release.bundle_sha256)
            except Exception:  # the server can't be reached
                pass
        return release, self._store.exists(release.bundle_sha256)

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

    # -- for sync --------------------------------------------------------------

    def check_incoming(
        self, state: dict[str, Any], head: dict[str, Any] | None
    ) -> None:
        """A release another device sent: its words must be ones a person's
        could have, its name free, and once made its content can't change."""
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

    # -- helpers ---------------------------------------------------------------

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


def _unreadable(e: Exception) -> str:
    if isinstance(e, FileNotFoundError):
        return (
            "The bundle is not on this computer, and the server hasn't got it "
            "either (or can't be reached)"
        )
    return "The bundle is not a readable zip"
