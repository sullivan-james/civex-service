"""Reaching stored files by name and hierarchy, the way a filesystem would.

Files are stored by content hash, so a person can't browse them as folders.
This module is the one rule for the *path* a file would have if they could:
the names of the records above it (an encounter, a recording), then the file's
own name. It is pure -- no store, no records -- so the Files view, the export,
the zip download and the CLI can't disagree about where a file is.

Where a file's bytes actually are (which volume, whether it can be read now) is
the store's answer, attached to each `FileItem` by `FileAccessService`.
"""

from __future__ import annotations

import dataclasses
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from civex.domain.exceptions import CivexError
from civex.domain.query import RecordQuery
from civex.domain.tables import TableSpec

# Characters no common filesystem accepts in a name (plus control characters).
_UNSAFE_RE = re.compile(r'[\\/\x00-\x1f:*?"<>|]')
# Windows device names: refused as a whole name, with or without an extension.
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
MAX_SEGMENT = 100  # characters; well inside the 255-byte limit of common filesystems

# How an export puts files in its folder (see `FileAccessService.export`):
#   link  a hard link to the stored file, in a folder on the drive that holds the
#         files. No copy, no extra space; it is the stored file under another name.
#   copy  a real copy, into a folder on one drive of your choosing.
EXPORT_MODES = ("link", "copy")

# How a selection's files are arranged in a folder:
#   tree     the hierarchy: a folder per record above each file (the default)
#   grouped  the hierarchy down to the record that holds the files, whose files
#            are gathered into one folder named for its kind
#            (Encounter/Recording/Selections/...), not a folder per record
#   flat     every file in one folder
# Where several records' files share a folder (grouped, flat), two different
# files with the same name are told apart by the name of the record that owns
# each.
LAYOUT_TREE = "tree"
LAYOUT_GROUPED = "grouped"
LAYOUT_FLAT = "flat"
LAYOUTS = (LAYOUT_TREE, LAYOUT_GROUPED, LAYOUT_FLAT)

# Where exports made without an explicit folder go: `exports/<name>` in the
# project, or `_exports/<name>` in a volume outside it (named so the volume's
# object scan, which reads only two-character hex folders, never sees it).
PROJECT = "project"
PROJECT_EXPORTS = "exports"
VOLUME_EXPORTS = "_exports"


class FilesUnavailableError(CivexError):
    """Part of a selection can't be reached right now (a drive that isn't
    connected). Carries the plan so the caller can show what and why, and let
    a person choose to go ahead with the rest."""

    kind = "files_unavailable"

    def __init__(self, plan: "FilePlan") -> None:
        super().__init__(plan.summary())
        self.plan = plan


class FilesScatteredError(CivexError):
    """The reachable files are on more than one drive, so no single folder can
    hard-link them all. Carries the plan; the way forward is to copy them onto
    one drive."""

    kind = "files_scattered"

    def __init__(self, plan: "FilePlan") -> None:
        shares = ", ".join(f"{v.volume}: {v.files}" for v in plan.by_volume)
        super().__init__(
            f"These files are on {len(plan.by_volume)} drives ({shares}). A linked "
            "folder has to be on the drive that holds its files, so it can't "
            "gather them. Copy them onto one drive instead."
        )
        self.plan = plan


class LinksNotPossibleError(CivexError):
    """A linked folder can't be made on the drive holding the files (a drive
    that can't hard link, such as exFAT/FAT32, or one marked read-only)."""

    kind = "links_not_possible"


@dataclass
class FileSelection:
    """Which files: the records `query` selects (or exactly `record_ids`, such as
    the rows a person has ticked), and which of their file fields (`fields`;
    None = every file field). `base` is a record id: paths start below it
    ("Recording 3/x.txt" when looking at Encounter 7). With `query.within`
    and no `base`, the `within` record is the base."""

    query: RecordQuery = field(default_factory=RecordQuery)
    record_ids: list[str] | None = None
    fields: list[str] | None = None
    base: str | None = None
    layout: str = LAYOUT_TREE
    # Only records of these kinds (schema names), when no single `query.schema`
    # is given: how an export that takes "any kind beneath" a schema stays within
    # that schema's own tree instead of every record in the collection.
    schemas: list[str] | None = None
    # Also the files of every record beneath each selected one: "these
    # encounters, and everything inside them". Without it, only the selected
    # records' own files.
    below: bool = False
    # The tables made beside the files (`tables`; each says what its rows are,
    # where it is written and its columns), and whether the files themselves are
    # taken (`files`: False is tables alone).
    tables: list[TableSpec] = field(default_factory=list)
    files: bool = True


@dataclass
class FileItem:
    path: str  # relative, "/"-separated; unique within a plan
    sha256: str
    filename: str  # the name the file carries (resolved from the field's template)
    size: int
    record_id: str
    record_name: str
    field: str
    # Where the content is, as the store reports it.
    volume: str | None = None
    state: str = "unknown"
    available: bool = False
    reason: str = ""
    fix: str = ""
    # The file on disk right now (only filled when asked for).
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "filename": self.filename,
            "size": self.size,
            "record_id": self.record_id,
            "record_name": self.record_name,
            "field": self.field,
            "volume": self.volume,
            "state": self.state,
            "available": self.available,
            "reason": self.reason,
            "fix": self.fix,
            "source": self.source,
        }


# Where a file is, as one word a person can filter by: the name of the drive
# that holds it (reachable or not), or one of these.
PLACE_SERVER = "server"  # another device added it; only the server has it
PLACE_MISSING = "missing"  # on no drive this project knows, and no server
# Filters that group places.
PLACE_HERE = "here"  # on a drive of this computer that can be read now
PLACE_UNREACHABLE = "unreachable"  # on a drive of this computer that can't


def place_of(item: FileItem) -> tuple[str, str]:
    """(place, kind) of a file: the drive holding it and whether it can be read
    now (`drive` / `unreachable`), or `server` / `missing`. The one rule for
    where a file is, behind the Files tab's summary, its Where filter and the
    actions that pick files by place."""
    if item.volume:
        return item.volume, ("drive" if item.available else "unreachable")
    if item.state == "remote":
        return PLACE_SERVER, "server"
    return PLACE_MISSING, "missing"


def in_place(item: FileItem, wanted: str) -> bool:
    """Whether a file is in `wanted`: a drive's name, `server`, `missing`, or
    the groups `here` (any readable drive) and `unreachable`."""
    place, kind = place_of(item)
    if wanted == PLACE_HERE:
        return kind == "drive"
    if wanted == PLACE_UNREACHABLE:
        return kind == "unreachable"
    return place == wanted


@dataclass
class PlaceSummary:
    """How much of a selection is in one place."""

    place: str
    kind: str  # drive | unreachable | server | missing
    files: int
    bytes: int
    reason: str = ""  # for an unreachable drive: why, in its own words
    fix: str = ""


@dataclass
class FileListing:
    """One page of a selection's files, with where all of them are."""

    total: int  # files matching (after the place and name filters)
    summary: list[PlaceSummary]  # every file of the selection, by place
    items: list[FileItem]
    # How many files of each kind (file field): {field, files, bytes}.
    kinds: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class UnavailableGroup:
    """The files a selection holds on one drive that can't be reached."""

    volume: str | None  # None: not recorded on any drive this project knows
    state: str
    reason: str
    fix: str
    files: int
    bytes: int
    records: list[str]  # names of the records affected (first few)


@dataclass
class VolumeShare:
    """How much of a plan's reachable files one drive holds."""

    volume: str
    files: int
    bytes: int


@dataclass
class PlannedTable:
    """One table an export will make: its file name and the folder it is written
    in ("" = the top), the kind of record its rows are, how many rows, and its
    columns."""

    name: str
    kind: str
    rows: int
    columns: list[str]
    folder: str = ""
    format: str = "csv"
    shape: str = "rows"
    # The record whose folder it is in (None = the top), and the records that are
    # its rows. Not serialised: the plan already holds them.
    holder_id: str | None = None
    members: list[Any] = field(default_factory=list, repr=False)

    @property
    def path(self) -> str:
        """Where it is in the export, "/"-separated."""
        return f"{self.folder}/{self.name}" if self.folder else self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "folder": self.folder,
            "path": self.path,
            "kind": self.kind,
            "rows": self.rows,
            "columns": self.columns,
            "format": self.format,
            "shape": self.shape,
        }


@dataclass
class FilePlan:
    """What a selection holds and how much of it can be reached now. Built
    before anything is made or opened, so a person is told what is out of
    reach first."""

    items: list[FileItem]
    unavailable: list[UnavailableGroup] = field(default_factory=list)
    # Same content listed twice in one folder, dropped from `items`.
    duplicates_dropped: int = 0
    # Where each record's file value is, for every value (a dropped repeat points
    # at the file that was kept): (record id, field) -> paths, in order. How an
    # export's spreadsheet says where the file is in its folder.
    paths: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    # The records the plan was made from, so a table of them needs no second
    # read of the selection. Never serialised.
    records: list[Any] = field(default_factory=list, repr=False)
    # The tables the selection asks for, beside the files.
    tables: list[PlannedTable] = field(default_factory=list)

    def paths_for(self, record_id: str, field_name: str) -> list[str]:
        return self.paths.get((record_id, field_name), [])

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def available(self) -> int:
        return sum(1 for i in self.items if i.available)

    @property
    def bytes(self) -> int:
        return sum(i.size for i in self.items)

    @property
    def available_bytes(self) -> int:
        return sum(i.size for i in self.items if i.available)

    @property
    def to_fetch(self) -> list[FileItem]:
        """Files only on the server (another device added them): an export
        downloads them first, so they don't make it incomplete."""
        return [i for i in self.items if i.state == "remote"]

    @property
    def complete(self) -> bool:
        return self.available + len(self.to_fetch) == self.total

    @property
    def by_volume(self) -> list[VolumeShare]:
        """The drives the reachable files are on, largest first."""
        shares: dict[str, VolumeShare] = {}
        for item in self.items:
            if item.available and item.volume:
                share = shares.setdefault(item.volume, VolumeShare(item.volume, 0, 0))
                share.files += 1
                share.bytes += item.size
        return sorted(shares.values(), key=lambda v: (-v.bytes, v.volume))

    @property
    def scattered(self) -> bool:
        """Reachable files on more than one drive: a linked folder can't hold them."""
        return len(self.by_volume) > 1

    @property
    def link_volume(self) -> str | None:
        """The one drive a linked folder would go on; None if there isn't one."""
        shares = self.by_volume
        return shares[0].volume if len(shares) == 1 else None

    def summary(self) -> str:
        if self.complete:
            return f"{self.total} file(s), all available."
        parts = []
        for g in self.unavailable:
            where = f"on '{g.volume}'" if g.volume else "not stored on any known drive"
            parts.append(f"{g.files} {where} ({g.reason or g.state})")
        return (
            f"{self.total - self.available} of {self.total} file(s) can't be "
            f"reached: {'; '.join(parts)}."
        )

    def to_dict(
        self, include_items: bool = True, offset: int = 0, limit: int | None = None
    ) -> dict[str, Any]:
        """The plan as the API sends it. A big selection's items go in pages
        (`offset`/`limit`) or not at all; the totals and the unreachable groups
        always cover the whole selection."""
        shown = self.items[offset : None if limit is None else offset + limit]
        return {
            "total": self.total,
            "available": self.available,
            "bytes": self.bytes,
            "available_bytes": self.available_bytes,
            "complete": self.complete,
            "scattered": self.scattered,
            "link_volume": self.link_volume,
            "by_volume": [
                {"volume": v.volume, "files": v.files, "bytes": v.bytes}
                for v in self.by_volume
            ],
            "duplicates_dropped": self.duplicates_dropped,
            "to_fetch": {
                "files": len(self.to_fetch),
                "bytes": sum(i.size for i in self.to_fetch),
            },
            "tables": [t.to_dict() for t in self.tables],
            "summary": self.summary(),
            "unavailable": [
                {
                    "volume": g.volume,
                    "state": g.state,
                    "reason": g.reason,
                    "fix": g.fix,
                    "files": g.files,
                    "bytes": g.bytes,
                    "records": g.records,
                }
                for g in self.unavailable
            ],
            "items": [i.to_dict() for i in shown] if include_items else [],
        }


@dataclass
class ExportResult:
    dest: str
    # Where it was made: a volume name, or "project". None for a folder chosen
    # by path.
    location: str | None = None
    linked: int = 0  # hard links: the stored file under another name
    copied: int = 0
    unchanged: int = 0  # already in place from an earlier export
    removed: int = 0  # in the earlier export, no longer selected
    tables: int = 0  # tables written beside the files
    # Files left out: not reachable when planned, or gone by the time they were made.
    missing: list[FileItem] = field(default_factory=list)

    @property
    def written(self) -> int:
        return self.linked + self.copied

    def to_dict(self) -> dict[str, Any]:
        return {
            "dest": self.dest,
            "location": self.location,
            "linked": self.linked,
            "copied": self.copied,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "tables": self.tables,
            "missing": [i.to_dict() for i in self.missing],
            "complete": not self.missing,
        }


@dataclass
class ExportInfo:
    """An export folder that is on disk now, for listing and cleaning up."""

    name: str
    location: str  # a volume name, or "project"
    path: str
    files: int
    # Space the folder takes: copies only (a link takes none). None when the
    # folder was made before this was recorded.
    bytes_on_disk: int | None
    linked: int | None
    copied: int | None
    updated: str | None  # ISO time of the last export into it

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class RemoveResult:
    path: str
    removed_files: int
    freed_bytes: int  # what copies gave back; links give back none
    # Files in the folder that the export didn't make (yours): left in place,
    # along with the folder.
    kept_files: int
    folder_removed: bool

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# --- names ---------------------------------------------------------------


def safe_segment(name: str | None, fallback: str = "_") -> str:
    """One folder or file name that any filesystem takes: unsafe characters
    replaced, no leading/trailing dots or spaces, Windows device names
    refused, and a length cap (keeping a file's extension)."""
    text = _UNSAFE_RE.sub("_", (name or "").strip()).strip(" .")
    if not text:
        return fallback
    stem, dot, ext = text.rpartition(".")
    if not dot or not stem or len(ext) > 12:
        stem, ext = text, ""
    else:
        ext = "." + ext
    if stem.split(".")[0].casefold() in _RESERVED:
        stem = "_" + stem
    if len(stem) + len(ext) > MAX_SEGMENT:
        stem = stem[: max(MAX_SEGMENT - len(ext), 1)].rstrip(" .") or "_"
    return stem + ext


def pluralize(word: str) -> str:
    """ "Selection" -> "Selections", "Study" -> "Studies", "Class" -> "Classes".
    Plain English rules: it names a folder, not a sentence."""
    if not word:
        return word
    lower = word.lower()
    if lower.endswith("y") and len(word) > 1 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def group_folder(kind: str) -> str:
    """The folder that gathers the files of every record of one kind in one place
    ("Selection" -> "Selections")."""
    return safe_segment(pluralize(kind), "Files")


def folder_segments(
    parents: dict[str, str | None], names: dict[str, str]
) -> dict[str, str]:
    """A folder name for each record. `parents` maps record id -> its parent's
    id (None at the top) and `names` id -> display name. Records that would
    share a name inside one parent -- compared without regard to case, since
    a Windows or macOS drive does -- each get a short id appended
    ("Recording 3~a1b2c3d4"); the rest keep their plain name. Deterministic
    for a given set of records."""
    by_slot: dict[tuple[str | None, str], list[str]] = {}
    for rid, parent in parents.items():
        by_slot.setdefault(
            (parent, safe_segment(names.get(rid), rid[:8]).casefold()), []
        ).append(rid)
    out: dict[str, str] = {}
    for (_, _), rids in by_slot.items():
        for rid in rids:
            plain = safe_segment(names.get(rid), rid[:8])
            out[rid] = plain if len(rids) == 1 else _tagged(plain, rid[:8])
    return out


def _tagged(name: str, tag: str) -> str:
    """`name~tag`, kept within the length cap."""
    room = MAX_SEGMENT - len(tag) - 1
    return f"{name[:room].rstrip(' .') or '_'}~{tag}"


def file_names_in_folder(
    entries: list[tuple[str, str] | tuple[str, str, str | None]],
) -> tuple[list[str | None], int]:
    """Names for files that share one folder. `entries` is (filename, sha256) or
    (filename, sha256, owner) per file, `owner` being the name of the record the
    file belongs to. Two files with the same name (any case) and different
    content are told apart: by `<owner> - <name>` when every one of them has a
    different owner, otherwise by `~<hash>` before the extension. The same name
    and content twice is one file -- the repeat comes back as None.
    Returns (names, repeats)."""
    groups: dict[str, list[int]] = {}
    for i, entry in enumerate(entries):
        groups.setdefault(safe_segment(entry[0], "file").casefold(), []).append(i)
    names: list[str | None] = [None] * len(entries)
    repeats = 0
    for idxs in groups.values():
        distinct = list(dict.fromkeys(entries[i][1] for i in idxs))
        owners = _owners_of(entries, idxs)
        seen: set[str] = set()
        for i in idxs:
            filename, sha = entries[i][0], entries[i][1]
            plain = safe_segment(filename, "file")
            if sha in seen:
                repeats += 1
                continue
            seen.add(sha)
            if len(distinct) == 1:
                names[i] = plain
            elif owners is not None:
                names[i] = safe_segment(f"{owners[sha]} - {plain}", plain)
            else:
                p = PurePosixPath(plain)
                stem, ext = (p.stem, p.suffix) if p.suffix else (plain, "")
                names[i] = _tagged(stem, sha[:8]) + ext
    return names, repeats


def _owners_of(
    entries: list[tuple[str, str] | tuple[str, str, str | None]], idxs: list[int]
) -> dict[str, str] | None:
    """Each different file's owner, if every one has one and no two share a name
    (so the owner can tell them apart); else None."""
    owner_of: dict[str, str] = {}
    for i in idxs:
        entry = entries[i]
        owner = entry[2] if len(entry) > 2 else None  # type: ignore[misc]
        if not owner:
            return None
        owner_of.setdefault(entry[1], owner)
    if len({o.casefold() for o in owner_of.values()}) != len(owner_of):
        return None
    return owner_of


def join_path(*segments: str) -> str:
    return posixpath.join(*segments) if segments else ""
