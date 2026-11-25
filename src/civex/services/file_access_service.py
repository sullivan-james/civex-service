"""Reaching stored files by name and hierarchy: plan a selection, then export it.

Files are stored by hash; people think in encounters and recordings. A
`FileSelection` says which files (the records the explorer is showing, the rows
ticked, everything under an encounter); `plan` names each one by its place in the
record hierarchy (`domain/file_access.py` is the one path rule) and says what can
be reached right now; `export` makes that tree on disk.

Nothing is made until the plan has been seen: `export` refuses a selection with
files out of reach (a drive that isn't connected) unless told to go ahead with the
rest, and then says exactly which were left out.
"""

from __future__ import annotations

from collections import Counter

import copy
import dataclasses
import json
import os
import posixpath
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from civex import __version__, file_modes, fs_locations
from civex.domain.dtos import FileRef, RecordDTO
from civex.domain import features
from civex.domain.field_descriptors import COMPUTED_DTYPES
from civex.domain.exceptions import (
    FeatureUnavailableError,
    NotFoundError,
    ValidationError,
)
from civex.domain.sync import not_on_server_yet
from civex.domain import geo as geo_rules
from civex.domain import tables as table_rules
from civex.domain import templating
from civex.domain.naming import display_label
from civex.domain.query import RecordQuery, RecordSet
from civex.domain.placement import STEP_COPY, STEP_MOVE, STEP_THERE
from civex.domain.transfers import KIND_FILES, TransferSpec
from civex.services.transfer_engine import Step, plan_steps
from civex.domain.file_refs import collect_sha256_refs
from civex.domain.file_access import (
    PLACE_SENT,
    PLACE_UNSENT,
    SERVER_STATES,
    server_state,
    copy_key,
    record_key,
    MovePlan,
    FileListing,
    PlaceSummary,
    in_place,
    place_of,
    EXPORT_MODES,
    LAYOUT_FLAT,
    LAYOUT_GROUPED,
    LAYOUT_TREE,
    LAYOUTS,
    PROJECT,
    PROJECT_EXPORTS,
    VOLUME_EXPORTS,
    ExportInfo,
    ExportResult,
    FileItem,
    FilePlan,
    FileSelection,
    FilesUnavailableError,
    LinksNotPossibleError,
    PlannedTable,
    RemoveResult,
    UnavailableGroup,
    file_names_in_folder,
    folder_segments,
    group_folder,
    safe_segment,
)
from civex.repositories.protocols import (
    FileReferenceRepository,
    ObjectStore,
    VolumeStore,
)
from civex.services.progress import Progress
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService
from civex.services.table_files import write_table

MARKER = ".civex-export.json"  # says a folder is ours, and what we put in it
# The layout of the marker file itself (not civex's version): bump when it changes.
MARKER_FORMAT = 2
MISSING_NOTE = "MISSING.txt"
# The marker's word for a file the export wrote itself (a table), as opposed to a
# link to, or copy of, a stored file.
GENERATED = "generated"
# Records per page when a table works out derived columns.
TABLE_PAGE = 500
# Records read at a time when a plan reads the ones that hold files.
HOLDERS_PAGE = 500
# How a file reaches a typed table: where it is on this computer, or its name.
FILES_PATH = "path"
FILES_NAME = "name"
FILE_FORMS = (FILES_PATH, FILES_NAME)
# How a link to another record reaches a typed table: its name, or its id.
REFERENCES_NAME = "name"
REFERENCES_ID = "id"
REFERENCE_FORMS = (REFERENCES_NAME, REFERENCES_ID)
_NOT_ON_DISK = "The file is not on the drive where it should be."
_SHOWN_RECORDS = 10  # record names listed per unreachable group


class FileAccessService:
    def __init__(
        self,
        records: RecordService,
        schemas: SchemaService,
        store: ObjectStore,
        civex_dir: Path,
        volumes: VolumeStore | None = None,
    ) -> None:
        self._records = records
        self._schemas = schemas
        self._store = store
        # The drives on this machine (the same store), where exports can be
        # made as folders of links or copies; None when files are in a bucket,
        # which offers a zip and nothing on disk.
        self._volumes = volumes
        self._civex_dir = civex_dir
        # Which live records use a file (for files shared with records not
        # picked); set by `build_local_context`.
        self.refs: FileReferenceRepository | None = None
        # Downloads files another device added (they are cited here but on no
        # drive here) from the authority, given their hashes and a callable told
        # how many have arrived; None when the project follows none. Injected
        # so this service doesn't know sync.
        self.fetch_missing: (
            Callable[
                [
                    list[str],
                    Callable[[int], None] | None,
                    str | None,
                    Callable[[int], None] | None,
                ],
                Any,
            ]
            | None
        ) = None
        # Removes this computer's copies of content the server holds (given the
        # hashes and whether only to count); None when the project follows no
        # server. Injected like `fetch_missing`.
        self.free_files: Callable[[list[str], bool], object] | None = None
        # Where files nobody can fetch yet still are, and what brings them
        # (`SyncService.not_here_reasons`); None when the project follows no
        # server. Injected like the others.
        self.why_not_here: Callable[[list[str]], dict[str, tuple[str, str]]] | None = (
            None
        )

    def with_records(self, records: Any) -> "FileAccessService":
        """This service reading its records from `records` instead of the live
        ones: anything with the record calls it makes (`get_many`, `get`,
        `file_values`, `ancestor_trails`, `stream_records`, `count_records`,
        `beneath`, `with_derived`), such as a release's frozen records
        (`release_records.FrozenRecords`). Everything else (the path rule,
        plans, folders, zips, the drives) is the same."""
        other = copy.copy(self)
        other._records = records
        return other

    def _drives(self) -> VolumeStore:
        """The drives files can be laid out on; a host without any answers
        that folders aren't offered here."""
        if self._volumes is None:
            raise FeatureUnavailableError(features.VOLUMES)
        return self._volumes

    # -- planning ------------------------------------------------------------

    def plan(
        self,
        selection: FileSelection,
        with_sources: bool = False,
        progress: Progress | None = None,
        fetch: bool = False,
    ) -> FilePlan:
        """Every file the selection holds, each with the path it would have and
        whether it can be reached now, and the tables it makes with where each is
        written. Reads only; makes nothing. With `with_sources`, each reachable
        file also carries where it is on disk (one stat per file, so only when
        asked for). With `fetch` (an export about to be made), files another
        device added that aren't here yet are first downloaded from the server,
        and the plan is of what is here then."""
        found = self._plan(selection, with_sources, progress)
        remote = [i.sha256 for i in found.to_fetch]
        if not (fetch and remote and self.fetch_missing):
            return found
        self._fetch(remote, progress, sizes=_sizes(found.to_fetch))
        return self._absent_now(self._plan(selection, with_sources, progress))

    def preview(self, selection: FileSelection, limit: int = 0) -> FilePlan:
        """A plan to show before anything is made: the totals of every file
        (how many, how big, on which drives, what can't be reached) with only
        the first `limit` files named and given their paths. The totals come
        from the database alone (`_held`, as the files list does), so a
        preview takes the same short while whatever the selection's size; a
        full `plan` names every file, which costs by the file. `FilePlan.named`
        says how many of its items carry a path (they come first).

        A selection that makes tables is planned in full: a table lists
        records, and the plan says how many rows each has."""
        if not self._lean(selection):
            return self.plan(selection)
        known = self._all_file_fields()
        held = self._held(selection)
        if held and selection.fields and not (known & set(selection.fields)):
            raise ValidationError(
                "None of the selected records has a file field named "
                + ", ".join(f"'{f}'" for f in selection.fields)
            )
        kinds = set(selection.fields) if selection.fields else None
        flat = selection.layout == LAYOUT_FLAT
        # In record order, each file once where a plan lists it once: the
        # same file under the same name in one record (anywhere, for one
        # folder of everything).
        seen: set[tuple[Any, ...]] = set()
        items: list[FileItem] = []
        dropped = 0
        for item, _, _ in sorted(held, key=lambda h: h[2][:2]):
            if kinds is not None and item.field not in kinds:
                continue
            spot = (
                None if flat else item.record_id,
                item.sha256,
                item.filename.casefold(),
            )
            if spot in seen:
                dropped += 1
                continue
            seen.add(spot)
            items.append(item)
        # Named: the first files, and a few records of each group that can't
        # be reached (they are named to the person).
        wanted = list(dict.fromkeys(i.record_id for i in items[:limit]))
        shown: dict[tuple[Any, ...], int] = {}
        for item in items:
            if item.available or item.state == "remote":
                continue
            group = (item.volume, item.state)
            if shown.get(group, 0) < _SHOWN_RECORDS and item.record_id not in wanted:
                shown[group] = shown.get(group, 0) + 1
                wanted.append(item.record_id)
        named: list[FileItem] = []
        if wanted:
            named = self._plan(
                FileSelection(
                    record_ids=wanted,
                    fields=selection.fields,
                    base=selection.base or selection.query.within,
                    layout=selection.layout,
                ),
                False,
                None,
                lead_with_collection=len({at[2] for _, _, at in held}) > 1,
            ).items
        records = set(wanted)
        first = set(dict.fromkeys(i.record_id for i in items[:limit]))
        # The first files (in path order), then the others that were named.
        front = sorted(
            named, key=lambda i: (i.record_id not in first, i.path.casefold())
        )
        rest = [i for i in items if i.record_id not in records]
        every = [*front, *rest]
        return FilePlan(
            items=every,
            unavailable=_unavailable_groups(every),
            duplicates_dropped=dropped,
            named=sum(1 for i in front if i.record_id in first),
        )

    def _absent_now(self, plan: FilePlan) -> FilePlan:
        """A plan made after downloading what was only on the server: a file
        still not here is one the server hasn't got either, so it can't be
        reached (not "to download"), and it says where it still is."""
        gone = [i.sha256 for i in plan.items if i.state == "remote"]
        if not gone:
            return plan
        why = self.why_not_here(gone) if self.why_not_here else {}
        for n, item in enumerate(plan.items):
            if item.state == "remote":
                reason, fix = why.get(item.sha256, not_on_server_yet(None))
                plan.items[n] = dataclasses.replace(
                    item, state="absent", available=False, reason=reason, fix=fix
                )
        plan.unavailable = _unavailable_groups(plan.items)
        return plan

    def _fetch(
        self,
        shas: list[str],
        progress: Progress | None,
        volume: str | None = None,
        sizes: dict[str, int] | None = None,
    ) -> Any:
        """Download these files from the server, as a stage of the work a
        person is watching (the same progress as the rest of it: how many
        files, how many bytes of how many, how fast); onto `volume` when they
        are being fetched to go there. `sizes` are the files' sizes as their
        records say, for the bytes to expect."""
        shas = list(dict.fromkeys(shas))
        if not shas or not self.fetch_missing:
            return None
        if progress:
            progress.phase(
                f"Downloading {len(shas)} file{'s' if len(shas) != 1 else ''} "
                "from the server",
                len(shas),
                sum((sizes or {}).get(sha, 0) for sha in shas),
            )
        return self.fetch_missing(
            shas,
            progress.advance if progress else None,
            volume,
            progress.add_bytes if progress else None,
        )

    def _plan(
        self,
        selection: FileSelection,
        with_sources: bool,
        progress: Progress | None,
        lead_with_collection: bool | None = None,
    ) -> FilePlan:
        """`lead_with_collection`: whether paths start with the collection's
        name, when the caller knows (it is planning part of a selection that
        spans several, or doesn't); None works it out from what is planned."""
        if selection.layout not in LAYOUTS:
            raise ValidationError(f"layout must be one of: {', '.join(LAYOUTS)}")
        flat = selection.layout == LAYOUT_FLAT
        grouped = selection.layout == LAYOUT_GROUPED
        placed = any(t.where for t in selection.tables)
        if placed and selection.layout != LAYOUT_TREE:
            raise ValidationError(
                "A table written in each folder needs the layout with a folder per "
                "record (tree)."
            )
        # Files alone: only the records that hold one are read (the catalog
        # says which), not every record of the selection.
        lean = self._lean(selection)
        records = (
            self._file_holders(selection, progress)
            if lean
            else self._select_records(selection, progress)
        )
        values: list[tuple[RecordDTO, str, dict[str, Any]]] = []
        if selection.files:
            values, known = self._records.file_values(records, selection.fields)
            if lean:
                # The kinds of record chosen aren't read, so the fields are
                # checked against every kind's.
                known = self._all_file_fields()
            # With no records yet there is nothing to check the fields against:
            # the export is empty for now, not wrong.
            if records and selection.fields and not (known & set(selection.fields)):
                raise ValidationError(
                    "None of the selected records has a file field named "
                    + ", ".join(f"'{f}'" for f in selection.fields)
                )
        base_id = self._base_id(selection)

        # The chain of records above each record that needs a folder, below the
        # base (if any): those holding files and, for tables written in folders,
        # every selected record (a flat layout has no folders, so it never looks
        # the ancestors up at all).
        needing = records if placed else [r for r, _, _ in values]
        empty = self._empty_holders(selection)
        needing = [*needing, *(r for rs in empty.values() for r in rs)]
        trails: dict[Any, list[RecordDTO]] = {}
        if not flat and needing:
            trails = self._records.ancestor_trails(
                list({r.id: r for r in needing}.values())
            )
            # A record met only as someone's ancestor has its own chain too: the
            # start of the trail it was found in. No further lookup.
            for trail in list(trails.values()):
                for i, above in enumerate(trail):
                    trails.setdefault(above.id, trail[:i])

        def chain_of(record: RecordDTO) -> list[RecordDTO]:
            chain = [*trails.get(record.id, []), record]
            if base_id is not None:
                ids = [str(c.id) for c in chain]
                if base_id in ids:
                    chain = chain[ids.index(base_id) + 1 :]
            return chain

        drafts = self._table_drafts(selection, records, trails, base_id, empty)

        chains = {} if flat else {str(r.id): chain_of(r) for r, _, _ in values}
        holders = {str(d.holder.id): d.holder for d in drafts if d.holder is not None}
        prefix_datasets = (
            not flat
            and base_id is None
            and (
                len(
                    {r.dataset_id for r, _, _ in values}
                    | {h.dataset_id for h in holders.values()}
                )
                > 1
                if lead_with_collection is None
                else lead_with_collection
            )
        )
        segments: dict[str, str] = {}
        if not flat:
            parents: dict[str, str | None] = {}
            names: dict[str, str] = {}

            def register(chain: list[RecordDTO], dataset_id: Any) -> None:
                above: str | None = None
                if prefix_datasets:
                    above = f"dataset:{dataset_id}"
                    parents[above] = None
                    names[above] = (chain[0].dataset_name if chain else None) or str(
                        dataset_id
                    )[:8]
                for node in chain:
                    rid = str(node.id)
                    parents[rid] = above
                    names[rid] = _record_name(node)
                    above = rid

            for record, _, _ in values:
                chain = chains[str(record.id)]
                # Grouped: the record that holds the file is not a folder; its
                # kind is (below), so only the records above it are named here.
                register(chain[:-1] if grouped else chain, record.dataset_id)
            for holder in holders.values():
                register(chain_of(holder), holder.dataset_id)
            segments = folder_segments(parents, names)
        kinds: dict[str, str] = {}  # a schema's name -> its folder, when grouped

        def kind_folder(record: RecordDTO) -> str:
            if record.schema_name not in kinds:
                kinds[record.schema_name] = group_folder(
                    self._schema_display(record.schema_name)
                )
            return kinds[record.schema_name]

        def folder_for(chain: list[RecordDTO], dataset_id: Any) -> str:
            ids = [str(c.id) for c in chain]
            if prefix_datasets:
                ids.insert(0, f"dataset:{dataset_id}")
            return "/".join(segments[i] for i in ids)

        def folder_of(record: RecordDTO) -> str:
            if flat:
                return ""
            chain = chains[str(record.id)]
            parts = folder_for(chain[:-1] if grouped else chain, record.dataset_id)
            # The base's own files stay at the top; everything else of a kind
            # shares one folder.
            if grouped and chain:
                parts = (
                    f"{parts}/{kind_folder(record)}" if parts else kind_folder(record)
                )
            return parts

        by_folder: dict[str, list[tuple[RecordDTO, str, dict[str, Any]]]] = {}
        for entry in values:
            by_folder.setdefault(folder_of(entry[0]), []).append(entry)

        items: list[FileItem] = []
        paths: dict[tuple[str, str], list[str]] = {}
        dropped = 0
        for folder, entries in by_folder.items():
            # Where several records share the folder, a clash is told apart by
            # the record that owns each file.
            shared = flat or grouped
            file_names, repeats = file_names_in_folder(
                [
                    (_file_name(ref), ref["sha256"], _record_name(record))
                    if shared
                    else (_file_name(ref), ref["sha256"])
                    for record, _, ref in entries
                ]
            )
            dropped += repeats
            kept: dict[str, str] = {}  # content -> the path it was given here
            for (record, field_name, ref), name in zip(entries, file_names):
                if name is None:  # a repeat: it is the file already kept
                    where = kept[ref["sha256"]]
                else:
                    where = f"{folder}/{name}" if folder else name
                    kept[ref["sha256"]] = where
                    location = ref.get("location") or {}
                    items.append(
                        FileItem(
                            path=where,
                            sha256=ref["sha256"],
                            filename=_file_name(ref),
                            size=int(ref.get("size") or 0),
                            record_id=str(record.id),
                            record_name=_record_name(record),
                            field=field_name,
                            volume=location.get("volume"),
                            state=location.get("state") or "unknown",
                            available=location.get("available") is True,
                            reason=location.get("reason") or "",
                            fix=location.get("fix") or "",
                            sent=location.get("sent"),
                        )
                    )
                paths.setdefault((str(record.id), field_name), []).append(where)
        items.sort(key=lambda i: i.path.casefold())
        planned = self._planned_tables(
            drafts,
            items,
            lambda d: (
                folder_for(chain_of(d.holder), d.holder.dataset_id)
                if d.holder is not None and not flat
                else ""
            ),
        )
        if with_sources:
            items = [self._with_source(i) for i in items]
        return FilePlan(
            items=items,
            unavailable=_unavailable_groups(items),
            duplicates_dropped=dropped,
            paths=paths,
            records=records,
            tables=planned,
        )

    # -- tables --------------------------------------------------------------

    def _kinds(self, selection: FileSelection, records: list[RecordDTO]) -> list[str]:
        """The kinds of record that get a table when none is chosen, in name order.
        Beside files, only the kinds that hold files (the table lists what the
        files belong to); on its own, every kind selected."""
        found = {r.schema_name for r in records}
        if selection.query.schema and selection.record_ids is None:
            found.add(
                selection.query.schema
            )  # a kind asked for has a table, even empty
        kinds = sorted(found)
        if not selection.files:
            return kinds
        return [k for k in kinds if self._file_columns(k)]

    def _file_field_set(self, kind: str) -> set[str]:
        return set(self._file_columns(kind))

    def _file_columns(self, schema_name: str) -> list[str]:
        return [
            rf.field.name
            for rf in self._schemas.collect_fields(self._schemas.get(schema_name))
            if rf.field.dtype in ("file", "file_list")
        ]

    def _columns_for(self, schema_name: str, wanted: list[str] | None) -> list[str]:
        """The columns of one kind's table: what was asked for that this kind has
        (a field, a `ref.field` join, or a record column), else the id and every
        field."""
        names = [
            rf.field.name
            for rf in self._schemas.collect_fields(self._schemas.get(schema_name))
        ]
        if wanted is None:
            return [*table_rules.DEFAULT_META, *names]
        return [
            c
            for c in dict.fromkeys(wanted)
            if c in table_rules.META_COLUMNS or c.partition(".")[0] in names
        ]

    def table_name(self, kind: str, fmt: str) -> str:
        """The table's file name in the export, from what it lists: the kind's
        plural, as the grouped layout names its folders (`Selections.csv`)."""
        return group_folder(self._schema_display(kind)) + table_rules.extension(fmt)

    def _table_drafts(
        self,
        selection: FileSelection,
        records: list[RecordDTO],
        trails: dict[Any, list[RecordDTO]],
        base_id: str | None,
        empty: dict[str, list[RecordDTO]],
    ) -> list[_Draft]:
        """The tables a selection asks for before they are given folders and
        names: for each, who holds it (the record whose folder it is written in,
        None for the top) and which records are its rows.

        A table's rows are the records of its kind among those the export takes,
        the ones above them, and (when the export takes what is beneath) the ones
        below: one pool, so "a table of recordings" works from an export of
        selections. A table written in each folder of a kind is cut from that pool
        by the nearest record of that kind at or above each row."""
        drafts: list[_Draft] = []
        for spec in selection.tables:
            if spec.general:
                for kind in self._kinds(selection, records):
                    drafts.append(
                        _Draft(
                            spec,
                            kind,
                            None,
                            [r for r in records if r.schema_name == kind],
                        )
                    )
                continue
            assert spec.kind is not None
            pool = _pool(spec.kind, records, trails, base_id)
            if not spec.where:
                drafts.append(_Draft(spec, spec.kind, None, pool))
                continue
            groups: dict[str, list[RecordDTO]] = {}
            holders: dict[str, RecordDTO] = {}
            for member in pool:
                full = [*trails.get(member.id, []), member]
                holder = next(
                    (n for n in reversed(full) if n.schema_name == spec.where), None
                )
                if holder is None:
                    continue
                if base_id is not None and base_id not in [
                    str(n.id) for n in full[: full.index(holder) + 1]
                ]:
                    continue  # above the base: not part of this export
                holders[str(holder.id)] = holder
                groups.setdefault(str(holder.id), []).append(member)
            if not spec.skip_empty:
                for node in empty.get(spec.where, []):
                    holders.setdefault(str(node.id), node)
            for hid, holder in holders.items():
                drafts.append(_Draft(spec, spec.kind, holder, groups.get(hid, [])))
        return drafts

    def _empty_holders(self, selection: FileSelection) -> dict[str, list[RecordDTO]]:
        """For tables that want a folder even with no rows: every record of the
        kind whose folder it is, in the place the export is run (its collection, or
        beneath the record it is run within). Only looked up when asked for."""
        wanted = {t.where for t in selection.tables if t.where and not t.skip_empty}
        found: dict[str, list[RecordDTO]] = {}
        for kind in wanted:
            query = dataclasses.replace(
                selection.query.for_kind(kind), filter_tree=None, where=[], search=None
            )
            found[str(kind)] = [
                r for page in self._records.stream_records(query) for r in page
            ]
        return found

    def _planned_tables(
        self,
        drafts: list[_Draft],
        items: list[FileItem],
        folder_of_holder: Callable[[_Draft], str],
    ) -> list[PlannedTable]:
        """Each table with its folder, its file name and its columns. A name is
        never one a file or folder in the same folder already has (compared
        without regard to case): it is given another."""
        used: dict[str, set[str]] = {}

        def claim(path: str) -> None:
            parts = path.split("/")
            for i in range(len(parts)):
                used.setdefault("/".join(parts[:i]), set()).add(parts[i].casefold())

        for item in items:
            claim(item.path)
        folders = {id(d): folder_of_holder(d) for d in drafts}
        for folder in folders.values():
            if folder:
                claim(folder)
        general = [d for d in drafts if d.spec.general]
        # A schema is looked up once however many tables are of it: a table per
        # recording is not a query per recording.
        columns_of = _memo(lambda kind, wanted: self._columns_for(kind, wanted))
        display_of = _memo(self._schema_display)
        out = []
        for d in drafts:
            # A kind asked for in the simple form has its table even when empty;
            # one written in each folder skips the folders with no rows (unless
            # asked to keep them).
            if not d.members and d.spec.skip_empty and not d.spec.general:
                continue
            columns = columns_of(d.kind, tuple(d.spec.columns or ()) or None)
            if not columns:
                continue
            folder = folders[id(d)]
            name = self._table_filename(d, len(general) == 1, display_of)
            stem, ext = posixpath.splitext(name)
            n = 1
            while name.casefold() in used.get(folder, set()):
                n += 1
                name = f"{stem} ({n}){ext}"
            used.setdefault(folder, set()).add(name.casefold())
            out.append(
                PlannedTable(
                    name=name,
                    kind=d.kind,
                    rows=len(d.members),
                    columns=columns,
                    folder=folder,
                    format=d.spec.format,
                    shape=d.spec.shape,
                    holder_id=str(d.holder.id) if d.holder is not None else None,
                    members=d.members,
                )
            )
        return out

    def _table_filename(
        self, d: _Draft, single: bool, display_of: Callable[[str], str]
    ) -> str:
        """A table's file name. The first form names it for its kind (or, when it
        is the only table and was given a name, that); otherwise a name template
        over the folder's record, else a default: a record's own fields are
        `Metadata`, a list is named for what it lists."""
        spec = d.spec
        ext = table_rules.extension(spec.format)
        if spec.general:
            if spec.name and single:
                return safe_segment(spec.name, "table") + ext
            return group_folder(display_of(d.kind)) + ext
        rendered = None
        if spec.name:
            values = d.holder.data if d.holder is not None else {}
            rendered = templating.render(
                spec.name,
                values,
                {
                    "schema": display_of(d.kind),
                    "id": str(d.holder.id)[:8] if d.holder is not None else "",
                },
                on_missing="fallback",
            )
        if rendered:
            return safe_segment(rendered, "table") + ext
        if spec.shape == table_rules.SHAPE_FIELDS:
            return "Metadata" + ext
        return group_folder(display_of(d.kind)) + ext

    def _derived_for(self, plan: FilePlan) -> dict[tuple[str, str], dict[str, Any]]:
        """The derived columns (inherited, joined) of every row of every table,
        worked out once per kind however many tables there are: (kind, record id)
        -> its derived values. A table per recording is not a lookup per table."""
        members: dict[str, dict[str, RecordDTO]] = {}
        columns: dict[str, list[str]] = {}
        for t in plan.tables:
            for m in t.members:
                members.setdefault(t.kind, {})[str(m.id)] = m
            wanted = columns.setdefault(t.kind, [])
            wanted.extend(
                c
                for c in t.columns
                if c not in table_rules.META_COLUMNS and c not in wanted
            )
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for kind, found in members.items():
            records = list(found.values())
            for start in range(0, len(records), TABLE_PAGE):
                for r in self._records.with_derived(
                    kind, records[start : start + TABLE_PAGE], columns[kind]
                ):
                    out[(kind, str(r.id))] = r.derived or {}
        return out

    def table_rows(
        self,
        selection: FileSelection,
        plan: FilePlan,
        table: PlannedTable,
        derived: dict[tuple[str, str], dict[str, Any]] | None = None,
        file_fields_of: Callable[[str], set[str]] | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """A table's rows, a page at a time. A column that holds files says where
        each file is in the export (the same path the plan gave it), so the table
        and the folder agree; a file column the export doesn't take shows the file's
        name. A field/value table gives each of its record's columns as a row."""
        file_fields = (file_fields_of or self._file_field_set)(table.kind)
        in_plan = (
            (
                file_fields
                if selection.fields is None
                else file_fields & set(selection.fields)
            )
            if selection.files
            else set()
        )
        fields = [c for c in table.columns if c not in table_rules.META_COLUMNS]

        def value_of(record: RecordDTO, c: str) -> Any:
            if c in table_rules.META_COLUMNS:
                return _record_column(record, c)
            known = (
                derived.get((table.kind, str(record.id)), {})
                if derived is not None
                else (record.derived or {})
            )
            value = known[c] if c in known else record.data.get(c)
            if c in in_plan:
                paths = plan.paths_for(str(record.id), c)
                if paths:
                    return paths if isinstance(value, list) else paths[0]
            if c in file_fields:
                return _display_filename(value)
            return value

        mine = table.members
        for start in range(0, len(mine), TABLE_PAGE):
            page = (
                mine[start : start + TABLE_PAGE]
                if derived is not None
                else self._records.with_derived(
                    table.kind, mine[start : start + TABLE_PAGE], fields
                )
            )
            if table.shape == table_rules.SHAPE_FIELDS:
                yield [
                    {"field": c, "value": value_of(record, c)}
                    for record in page
                    for c in table.columns
                ]
            else:
                yield [
                    {c: value_of(record, c) for c in table.columns} for record in page
                ]

    def write_tables(
        self, selection: FileSelection, plan: FilePlan, folder: Path
    ) -> list[tuple[str, Path]]:
        """Write the plan's tables into `folder`, each in its own folder of the
        export; returns (path in the export, file on disk) for each."""
        made = []
        derived = self._derived_for(plan)
        file_fields_of = _memo(self._file_field_set)
        for table in plan.tables:
            where = (
                folder.joinpath(*table.folder.split("/")) if table.folder else folder
            )
            where.mkdir(parents=True, exist_ok=True)
            path = where / table.name
            # Written beside, then moved into place: if an earlier export left a
            # hard link here, the link is replaced, never written through to the
            # stored file it is.
            scratch = path.with_name(path.name + ".part")
            write_table(
                scratch,
                table.format,
                table_rules.FIELD_COLUMNS
                if table.shape == table_rules.SHAPE_FIELDS
                else table.columns,
                self.table_rows(selection, plan, table, derived, file_fields_of),
                sheet=table.kind,
            )
            os.replace(scratch, path)
            made.append((table.path, path))
        return made

    # -- typed rows for Python (civex.open) ----------------------------------

    def typed_rows(
        self,
        query: RecordQuery,
        *,
        columns: list[str] | None = None,
        geo: str = table_rules.GEO_SPLIT,
        files: str = FILES_PATH,
        references: str = REFERENCES_NAME,
        page_size: int = TABLE_PAGE,
    ) -> Iterator[list[dict[str, Any]]]:
        """The records `query` lists (one kind: `query.schema`), a page at a
        time, as rows of Python values: the table an export would write, made
        by the same `table_rows` with the same columns (`columns`: field names,
        fields of the records above, `ref.field` joins, `META_COLUMNS`; None =
        the id and every field), each cell in `domain/tables`' Python form
        rather than as text. `geo` is `split` (the GeoJSON dict, plus
        `<column>_lat`/`<column>_lon` for points), `geojson` or `wkt`; `files`
        is `path` (where the file is on this computer, else its name) or
        `name`; `references` is `name` (the record's name) or `id`. Nothing is
        changed and nothing downloaded."""
        return self._typed(query, columns, geo, files, references, page_size)[2]

    def frame(
        self,
        query: RecordQuery,
        *,
        columns: list[str] | None = None,
        geo: str = table_rules.GEO_SPLIT,
        files: str = FILES_PATH,
        references: str = REFERENCES_NAME,
    ) -> Any:
        """`typed_rows` as a pandas DataFrame, each column of its type: whole
        numbers `Int64` (blanks stay blank), decimals `float64`, true/false
        `boolean`, dates and times `datetime64` (times in UTC), choices
        `category`, text `string`, lists and locations as objects. A decimal
        field's unit is in `df.attrs["units"]` ({column: unit}) and every
        column's civex type in `df.attrs["types"]`. Read a page at a time, so
        the memory used is the DataFrame's own."""
        pd = _pandas()
        names, types, pages = self._typed(
            query, columns, geo, files, references, TABLE_PAGE
        )
        values: dict[str, list[Any]] = {n: [] for n in names}
        for page in pages:
            for row in page:
                for n in names:
                    values[n].append(row.get(n))
        df = pd.DataFrame(
            {n: _pandas_column(pd, values[n], *types[n]) for n in names},
            columns=names,
        )
        df.attrs["units"] = {
            n: r["unit"]
            for n, (dtype, r) in types.items()
            if dtype == "float" and r.get("unit")
        }
        df.attrs["types"] = {n: dtype for n, (dtype, _) in types.items()}
        return df

    def _typed(
        self,
        query: RecordQuery,
        wanted: list[str] | None,
        geo_form: str,
        files: str,
        references: str,
        page_size: int,
    ) -> tuple[
        list[str],
        dict[str, tuple[str, dict[str, Any]]],
        Iterator[list[dict[str, Any]]],
    ]:
        """The column names of a typed table, each one's civex type and
        restrictions (what it is converted by), and its rows: checked before
        anything is read, so a wrong argument says so at once."""
        if not query.schema:
            raise ValidationError("A table is of one kind of record: name its schema.")
        if geo_form not in table_rules.GEO_FORMS:
            raise ValidationError(f"geo is one of: {', '.join(table_rules.GEO_FORMS)}.")
        if files not in FILE_FORMS:
            raise ValidationError(f"files is one of: {', '.join(FILE_FORMS)}.")
        if references not in REFERENCE_FORMS:
            raise ValidationError(
                f"references is one of: {', '.join(REFERENCE_FORMS)}."
            )
        kind = query.schema
        columns = self._columns_for(kind, wanted)
        if wanted is not None:
            unknown = [c for c in dict.fromkeys(wanted) if c not in columns]
            if unknown:
                raise ValidationError(
                    f"'{kind}' has no column "
                    + ", ".join(f"'{c}'" for c in unknown)
                    + " (a field, a field of a record above, a reference's "
                    "`ref.field`, or one of: "
                    + ", ".join(table_rules.META_COLUMNS)
                    + ")."
                )
        types = self._column_types(kind, columns, references)
        names: list[str] = []
        for c in columns:
            names.append(c)
            if geo_form == table_rules.GEO_SPLIT and types[c][0] == "geo":
                for part in (f"{c}_lat", f"{c}_lon"):
                    if part not in columns:
                        names.append(part)
                        types[part] = ("float", {})
        return (
            names,
            types,
            self._typed_pages(
                query, kind, columns, types, geo_form, files, references, page_size
            ),
        )

    def _column_types(
        self, kind: str, columns: list[str], references: str
    ) -> dict[str, tuple[str, dict[str, Any]]]:
        """Each column's civex type and restrictions: a record column's from
        `META_DTYPES`, a field's own, a join's from the field it reaches."""
        fields = {
            rf.field.name: rf.field
            for rf in self._schemas.collect_fields(self._schemas.get(kind))
        }
        out: dict[str, tuple[str, dict[str, Any]]] = {}
        for c in columns:
            if c in table_rules.META_COLUMNS:
                out[c] = (table_rules.META_DTYPES[c], {})
                continue
            found = fields.get(c)
            if found is None:  # `ref.field`
                ref_name, _, target_name = c.partition(".")
                ref = fields[ref_name]
                target_schema = (
                    ref.restrictions.get("schema") if ref.dtype == "reference" else None
                )
                found = (
                    next(
                        (
                            rf.field
                            for rf in self._schemas.collect_fields(
                                self._schemas.get(target_schema)
                            )
                            if rf.field.name == target_name
                        ),
                        None,
                    )
                    if target_schema
                    else None
                )
                if found is None:
                    raise ValidationError(
                        f"'{c}' reaches no field: '{ref_name}' must be a link to "
                        "one kind of record that has a field "
                        f"'{target_name}'."
                    )
            rules = dict(found.restrictions or {})
            if found.dtype in COMPUTED_DTYPES:
                # A formula's column is of the type it gives, with its unit.
                out[c] = (
                    rules.get("result") or "string",
                    {"unit": rules["unit"]} if rules.get("unit") else {},
                )
                continue
            out[c] = (found.dtype, rules)
        return out

    def _typed_pages(
        self,
        query: RecordQuery,
        kind: str,
        columns: list[str],
        types: dict[str, tuple[str, dict[str, Any]]],
        geo_form: str,
        files: str,
        references: str,
        page_size: int,
    ) -> Iterator[list[dict[str, Any]]]:
        selection = FileSelection(query=query, files=files == FILES_PATH)
        fields = [c for c in columns if c not in table_rules.META_COLUMNS]
        file_columns = [c for c in fields if types[c][0] in ("file", "file_list")]
        ref_columns = [
            c for c in fields if types[c][0] in ("reference", "reference_list")
        ]
        geo_columns = [c for c in columns if types[c][0] == "geo"]
        for page in self._records.stream_records(query, page_size=page_size):
            page = self._records.with_derived(kind, page, fields)
            derived = {(kind, str(r.id)): r.derived or {} for r in page}

            def raw(record: RecordDTO, c: str) -> Any:
                known = derived[(kind, str(record.id))]
                return known[c] if c in known else record.data.get(c)

            plan = FilePlan(
                items=[],
                paths=self._local_paths(page, file_columns, raw)
                if files == FILES_PATH
                else {},
            )
            names = (
                self._reference_names(page, ref_columns, raw)
                if references == REFERENCES_NAME
                else {}
            )
            table = PlannedTable(
                name="",
                kind=kind,
                rows=len(page),
                columns=columns,
                format="json",
                members=page,
            )
            out: list[dict[str, Any]] = []
            for rows in self.table_rows(selection, plan, table, derived):
                for row in rows:
                    for c in ref_columns:
                        row[c] = _named(row[c], names)
                    typed = {
                        c: table_rules.cell(
                            v, table_rules.PYTHON, *types[c], geo_form=geo_form
                        )
                        for c, v in row.items()
                    }
                    for c in geo_columns:
                        lat_lon = geo_rules.point_lat_lon(row[c])
                        for part, v in zip(("_lat", "_lon"), lat_lon or (None, None)):
                            if c + part in types and c + part not in columns:
                                typed[c + part] = v
                    out.append(typed)
            yield out

    def _local_paths(
        self,
        page: list[RecordDTO],
        file_columns: list[str],
        raw: Callable[[RecordDTO, str], Any],
    ) -> dict[tuple[str, str], list[str]]:
        """(record id, column) -> each file's path on this computer, or its name
        when it isn't on a drive that can be read now (unplugged, only on the
        server, files in a bucket). A record's own files say where they are
        already (`location`); one from a record above is looked up by content,
        once for the page."""
        if self._volumes is None or not file_columns:
            return {}
        volumes = self._volumes
        cells = [
            (r, c, [v for v in _as_list(raw(r, c)) if isinstance(v, dict)])
            for r in page
            for c in file_columns
        ]
        unstamped = {
            ref["sha256"]
            for _, _, refs in cells
            for ref in refs
            if "location" not in ref and ref.get("sha256")
        }
        located = self._store.locate_volumes(unstamped) if unstamped else {}
        reachable = _memo(lambda v: self._store.volume_status(v).reachable)

        def volume_of(ref: dict[str, Any]) -> str | None:
            location = ref.get("location")
            if location is not None:
                return location.get("volume") if location.get("available") else None
            volume = located.get(ref.get("sha256") or "")
            return volume if volume and reachable(volume) else None

        out: dict[tuple[str, str], list[str]] = {}
        for record, c, refs in cells:
            paths = []
            for ref in refs:
                volume = volume_of(ref)
                paths.append(
                    str(volumes.path_on(ref["sha256"], volume))
                    if volume
                    else _file_name(ref)
                )
            if paths:
                out[(str(record.id), c)] = paths
        return out

    def _reference_names(
        self,
        page: list[RecordDTO],
        ref_columns: list[str],
        raw: Callable[[RecordDTO, str], Any],
    ) -> dict[str, str]:
        """Record id -> its name, for every record a page's reference columns
        point at: the labels the records came with, and one lookup for those a
        record above or a join reached."""
        names: dict[str, str] = {}
        wanted: set[str] = set()
        for record in page:
            labels = record.reference_labels or {}
            for c in ref_columns:
                for target in _as_list(raw(record, c)):
                    if not isinstance(target, str):
                        continue
                    if labels.get(target):
                        names[target] = str(labels[target])
                    else:
                        wanted.add(target)
        wanted -= set(names)
        if wanted:
            for found in self._records.get_many(sorted(wanted)):
                if found.natural_name:
                    names[str(found.id)] = found.natural_name
        return names

    def _schema_display(self, schema_name: str) -> str:
        """A kind of record as a person reads it ("Selection", "Contour File")."""
        try:
            schema = self._schemas.get(schema_name)
            return display_label(schema.name, schema.label)
        except NotFoundError:  # a trashed schema: records keep their name for it
            return display_label(schema_name, None)

    def _source(self, item: FileItem) -> Path:
        """Where a reachable file is on disk, from the volume the inventory
        already named -- never a search across volumes."""
        assert item.volume is not None
        return self._drives().path_on(item.sha256, item.volume)

    def _with_source(self, item: FileItem) -> FileItem:
        if not item.available or item.volume is None:
            return item
        path = self._source(item)
        try:
            path.stat()
        except OSError:
            return _gone(item)
        return dataclasses.replace(item, source=str(path))

    def _lean(self, selection: FileSelection) -> bool:
        """Whether a plan of this selection needs only the records that hold
        files: it takes files and makes no table (a table lists records with
        none). Not for records read from elsewhere (`with_records`: a
        release's are in memory already)."""
        return (
            selection.files
            and not selection.tables
            and hasattr(self._records, "holding_files")
        )

    def _all_file_fields(self) -> set[str]:
        return {
            f.name
            for s in self._schemas.list_all()
            for f in s.fields
            if f.dtype in ("file", "file_list")
        }

    def _file_holders(
        self, selection: FileSelection, progress: Progress | None
    ) -> list[RecordDTO]:
        """The selection's records that hold a file, in full: which they are
        comes from the catalog (one statement, `holding_files`), and only
        they are read, a page at a time. So a plan costs by its files, not by
        the records they are among."""
        ids = self._records.holding_files(self._record_set(selection))
        if progress:
            progress.phase("Finding files", len(ids))
        found: list[RecordDTO] = []
        for start in range(0, len(ids), HOLDERS_PAGE):
            found.extend(self._records.get_many(ids[start : start + HOLDERS_PAGE]))
            if progress:
                progress.advance(len(found))
        return found

    def _select_records(
        self, selection: FileSelection, progress: Progress | None = None
    ) -> list[RecordDTO]:
        allowed = set(selection.schemas) if selection.schemas else None
        if selection.record_ids is not None:
            picked = self._records.get_many(selection.record_ids)
            if progress:
                progress.phase("Finding files", len(picked))
                progress.advance(len(picked))
            return self._with_beneath(picked, selection, allowed, progress)
        query = selection.query
        found: list[RecordDTO] = []
        if query.within and not query.schema:
            # "Everything under this record": its own files and those of every
            # record of every (allowed) schema beneath it.
            anchor = self._records.get(query.within)
            below = [
                d.name
                for d, _ in self._schemas.descendants(
                    self._schemas.get(anchor.schema_name)
                )
                if allowed is None or d.name in allowed
            ]
            if allowed is None or anchor.schema_name in allowed:
                found.append(anchor)
            queries = [query.for_kind(name) for name in below]
        elif allowed and not query.schema:
            # Several kinds, whole collection: each kind in turn.
            queries = [query.for_kind(name) for name in selection.schemas or []]
        else:
            queries = [query]
            if selection.with_within and query.within and query.schema:
                # The record the list is inside: its own files too.
                found.append(self._records.get(query.within))
        if progress:
            # How many records there are to go through, so it can say how far.
            progress.phase(
                "Finding files", sum(self._records.count_records(q) for q in queries)
            )
            progress.advance(len(found))
        for q in queries:
            for page in self._records.stream_records(q):
                found.extend(page)
                if progress:
                    progress.advance(len(found))
        return self._with_beneath(found, selection, allowed, progress)

    def _with_beneath(
        self,
        found: list[RecordDTO],
        selection: FileSelection,
        allowed: set[str] | None,
        progress: Progress | None,
    ) -> list[RecordDTO]:
        """The records, plus (when asked) everything beneath them, then narrowed
        to the kinds asked for: "only records of these kinds" means the records
        chosen as well as the ones found beneath them."""
        everything = found
        if selection.below and found:
            # Without tables, only the records holding files are used (folder
            # names come from their ancestors, looked up apart): the rest are
            # walked through, not put in full form.
            beneath = self._records.beneath(
                found,
                (lambda n: progress.advance(n)) if progress else None,
                keep=None
                if selection.tables or not selection.files
                else (lambda r: bool(collect_sha256_refs(r.data))),
            )
            if selection.record_ids is None and selection.query.filter_tree:
                beneath = self._as_listed(beneath, selection.query)
            everything = [*found, *beneath]
        if allowed is not None:
            everything = [r for r in everything if r.schema_name in allowed]
        return everything

    def _as_listed(
        self, beneath: list[RecordDTO], query: RecordQuery
    ) -> list[RecordDTO]:
        """Of the records beneath those a filtered selection chose, the ones the
        record list would list too, given the same filter: a record of each
        kind only if the filter, run for that kind (the explorer's own query,
        so AND, OR and conditions on parents or children mean what they mean
        there), lists it. "Encounters with a Selection whose contour file is
        empty" then takes those Selections' files, not every Selection's. One
        query per kind beneath."""
        kinds = {r.schema_name for r in beneath}
        listed: set[uuid.UUID] = set()
        for kind in kinds:
            for page in self._records.stream_records(query.for_kind(kind)):
                listed.update(r.id for r in page)
        return [r for r in beneath if r.id in listed]

    def _base_id(self, selection: FileSelection) -> str | None:
        ref = selection.base or selection.query.within
        if not ref:
            return None
        try:
            return str(self._records.get(ref).id)
        except NotFoundError:
            raise NotFoundError(f"Record '{ref}' not found") from None

    # -- where exports go ----------------------------------------------------

    def _in_project(self, volume: str) -> bool:
        if self._volumes is None:
            return False
        try:
            root = self._volumes.volume_path(volume).resolve()
        except (KeyError, OSError):
            return False
        return root.is_relative_to(self._civex_dir.parent.resolve())

    def location_of(self, volume: str) -> str:
        """Where exports for files on `volume` go: "project" for a volume inside
        the project folder, else the volume itself."""
        return PROJECT if self._in_project(volume) else volume

    def exports_root(self, location: str) -> Path:
        """The folder exports live in: `<project>/_civex/exports`, or
        `<volume>/_exports` on a volume outside the project."""
        if location == PROJECT:
            return self._civex_dir / PROJECT_EXPORTS
        if location not in self._drives().volume_names():
            raise NotFoundError(f"There is no drive called '{location}'.")
        if self._in_project(location):
            return self._civex_dir / PROJECT_EXPORTS
        return self._drives().volume_path(location) / VOLUME_EXPORTS

    def destination(self, location: str, name: str | None) -> Path:
        """The folder an export called `name` has at `location`. The same name
        gives the same folder, so opening a view again refreshes it instead of
        piling up copies."""
        return self.exports_root(location) / safe_segment(name, "files")

    def save_to(
        self,
        folder: str | None,
        filename: str,
        write: Callable[[Path], Any],
    ) -> Path:
        """Put one file civex makes (a copy of the project, a release's) in a
        folder of this computer: any folder a person chose (an external drive,
        a shared folder; it need not be one of the project's drives), or the
        project's own exports folder when none is named. `write(path)` makes
        it; it appears under its name only once whole. Answers where it is."""
        if folder:
            root = Path(fs_locations.normalise(folder))
            if not root.is_dir():
                raise NotFoundError(f"There is no folder '{folder}'.")
        else:
            root = self.exports_root(PROJECT)
            root.mkdir(parents=True, exist_ok=True)
        dest = root / safe_segment(filename, "file")
        part = dest.with_name(dest.name + ".part")
        try:
            write(part)
            file_modes.replace(part, dest)
        except PermissionError:
            raise ValidationError(f"'{root}' can't be written to.") from None
        finally:
            part.unlink(missing_ok=True)
        return dest

    def _check_writable(self, location: str) -> None:
        if location == PROJECT:
            return
        status = self._store.volume_status(location)
        if not status.writable:
            raise LinksNotPossibleError(
                f"'{location}' can't be written to now "
                f"({status.reason or status.state}). {status.fix}".strip()
            )

    # -- exporting -----------------------------------------------------------

    def export_managed(
        self,
        selection: FileSelection,
        name: str | None,
        mode: str = "link",
        volume: str | None = None,
        allow_partial: bool = False,
        plan: FilePlan | None = None,
        progress: Progress | None = None,
    ) -> ExportResult:
        """Export into civex's own exports folder. `link` puts it on the drive
        that holds most of the files, linking what it can and copying the rest;
        `copy` puts real copies on `volume` (or in the project if none is
        named), wherever the files are. Both can be cleaned up with
        `list_exports` / `remove_export`."""
        if mode not in EXPORT_MODES:
            raise ValidationError(f"mode must be one of: {', '.join(EXPORT_MODES)}")
        self._drives()  # folders of links or copies need drives
        plan = plan or self.plan(selection, progress=progress, fetch=True)
        if not plan.complete and not allow_partial:
            raise FilesUnavailableError(plan)
        if mode == "link":
            location = (
                self.location_of(plan.link_volume) if plan.link_volume else PROJECT
            )
        else:
            location = PROJECT if volume in (None, "", PROJECT) else volume
            if location not in (PROJECT, *self._drives().volume_names()):
                raise NotFoundError(f"There is no drive called '{location}'.")
        if plan.items or plan.tables:
            self._check_writable(location)
        return self.export(
            selection,
            self.destination(location, name),
            mode,
            allow_partial,
            plan,
            location=location,
            progress=progress,
        )

    def export(
        self,
        selection: FileSelection,
        dest: Path,
        mode: str = "link",
        allow_partial: bool = False,
        plan: FilePlan | None = None,
        location: str | None = None,
        progress: Progress | None = None,
    ) -> ExportResult:
        """Make the selection's folder tree at `dest`.

        Nothing is made, and an error says why, if any file is out of reach and
        `allow_partial` is not set (`FilesUnavailableError`), or `dest` hasn't
        room for the copies it needs. `link` makes a hard link wherever one can
        be made (a file on the same drive as `dest`, a drive that supports them)
        and a copy of every other file, so how the files are spread over drives
        never stops a folder being made; `copy` copies everything. Running it
        again on the same folder brings it up to date: what is there is left,
        what is new is added, what is no longer selected is removed -- but only
        in a folder an earlier export made, never one that holds other files. A
        link *is* the stored file, so it is made read-only
        (`file_modes.make_read_only`); a copy is yours to change."""
        if mode not in EXPORT_MODES:
            raise ValidationError(f"mode must be one of: {', '.join(EXPORT_MODES)}")
        self._drives()  # folders of links or copies need drives
        plan = plan or self.plan(selection, progress=progress, fetch=True)
        if not plan.complete and not allow_partial:
            raise FilesUnavailableError(plan)

        dest = Path(dest)
        previous = _read_marker(dest)
        if dest.exists():
            if not dest.is_dir():
                raise ValidationError(f"{dest} is not a folder.")
            if previous is None and any(dest.iterdir()):
                raise ValidationError(
                    f"{dest} already holds other files. Choose an empty folder "
                    "(or one a civex export made), so nothing of yours is touched."
                )
        previous = previous or {}
        reachable = [i for i in plan.items if i.available and i.volume]
        # Which drives' files can be linked at dest: one try per drive.
        linkable: dict[str, bool] = {}
        if mode == "link":
            for item in reachable:
                if item.volume and item.volume not in linkable:
                    linkable[item.volume] = self._can_link(self._source(item), dest)

        def how_now(item: FileItem) -> str:
            return "hardlinked" if linkable.get(item.volume or "") else "copied"

        def in_place(item: FileItem) -> bool:
            # What an earlier export left is kept if it is made as this one
            # would make it: a copy turns into a link once the file can be
            # linked (freeing its space), and a link into a copy for `copy`.
            entry = previous.get(item.path)
            return bool(
                entry and entry["sha"] == item.sha256 and entry["how"] == how_now(item)
            )

        self._check_room(
            dest,
            location,
            sum(
                i.size
                for i in reachable
                if not in_place(i) and not linkable.get(i.volume or "")
            ),
        )
        dest.mkdir(parents=True, exist_ok=True)

        result = ExportResult(dest=str(dest), location=location)
        kept: dict[str, dict[str, Any]] = {}
        handled = 0
        if progress:
            progress.phase("Copying files", len(plan.items))
        # Work a folder at a time: one listing of what an earlier export left
        # there (none for a fresh folder) and one mkdir, not a stat and a mkdir
        # per file.
        earlier_folders = {posixpath.dirname(p) for p in previous}
        folders: dict[str, list[FileItem]] = {}
        for item in plan.items:
            folders.setdefault(posixpath.dirname(item.path), []).append(item)
        for folder, items in folders.items():
            where = dest.joinpath(*folder.split("/")) if folder else dest
            present = _present(where) if folder in earlier_folders else set()
            made = where.is_dir() if present else False
            for item in items:
                handled += 1
                if progress:
                    progress.advance(handled)
                name = posixpath.basename(item.path)
                if in_place(item) and name in present:
                    kept[item.path] = previous[item.path]
                    result.unchanged += 1
                    continue
                if not item.available:
                    result.missing.append(item)
                    continue
                try:
                    source = self._source(item)
                    if not made:
                        where.mkdir(parents=True, exist_ok=True)
                        made = True
                    how = _place(
                        source,
                        where / name,
                        "link" if how_now(item) == "hardlinked" else "copy",
                    )
                except FileNotFoundError:
                    result.missing.append(_gone(item))
                    continue
                except OSError as e:
                    result.missing.append(
                        dataclasses.replace(
                            item, available=False, reason=f"Could not be written: {e}"
                        )
                    )
                    continue
                kept[item.path] = {"sha": item.sha256, "how": how, "size": item.size}
                if how == "hardlinked":
                    result.linked += 1
                else:
                    result.copied += 1

        for name, table_file in self.write_tables(selection, plan, dest):
            kept[name] = {
                "sha": "",
                "how": GENERATED,
                "size": table_file.stat().st_size,
            }
            result.tables += 1

        for path in previous:
            if path not in kept:
                _remove(dest, path)
                result.removed += 1
        _write_marker(dest, kept, mode)
        _write_missing_note(dest, result.missing)
        return result

    def _can_link(self, source: Path, dest: Path) -> bool:
        """Whether a hard link to `source` can be made at `dest`, tried with a
        throwaway name in the nearest folder that exists, before anything is
        built. Not when they are on different drives, or the drive can't hold
        links (exFAT, FAT32); those files are copied instead."""
        anchor = dest
        while not anchor.exists() and anchor != anchor.parent:
            anchor = anchor.parent
        probe = anchor / f".civex-link-probe-{os.getpid()}"
        try:
            os.link(source, probe)
        except FileNotFoundError:
            return True  # the file itself is gone; the build reports that per file
        except OSError:
            return False
        else:
            file_modes.remove(probe, missing_ok=True)
        return True

    def _check_room(self, dest: Path, location: str | None, need: int) -> None:
        if need <= 0:
            return
        free: int | None
        if (
            location
            and location != PROJECT
            and location in self._drives().volume_names()
        ):
            free = self._drives().room_on(location)
        else:
            anchor = dest
            while not anchor.exists() and anchor != anchor.parent:
                anchor = anchor.parent
            try:
                free = shutil.disk_usage(anchor).free
            except OSError:
                free = None
        if free is not None and need > free:
            raise ValidationError(
                f"Not enough room: copying needs {_size(need)} and "
                f"{_size(free)} is free"
                + (f" on '{location}'." if location else " there.")
            )

    # -- looking after exports -----------------------------------------------

    def _export_roots(self) -> list[tuple[str, Path]]:
        if self._volumes is None:  # no drives, so no folders were ever made
            return []
        roots = [(PROJECT, self._civex_dir / PROJECT_EXPORTS)]
        for volume in self._volumes.volume_names():
            if (
                not self._in_project(volume)
                and self._volumes.volume_status(volume).reachable
            ):
                roots.append(
                    (volume, self._volumes.volume_path(volume) / VOLUME_EXPORTS)
                )
        return roots

    def list_exports(self) -> list[ExportInfo]:
        """Every export folder civex made in its own places (the project, and
        each drive that's connected), newest first. Reads the folders directly
        inside those places and each one's marker, never the files within. A
        drive that isn't connected can't be looked in."""
        found: list[ExportInfo] = []
        for location, root in self._export_roots():
            try:
                with os.scandir(root) as entries:
                    folders = [e for e in entries if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            for entry in folders:
                info = _describe(Path(entry.path), location)
                if info is not None:
                    found.append(info)
        return sorted(found, key=lambda e: e.updated or "", reverse=True)

    def remove_export(self, path: str | Path) -> RemoveResult:
        """Delete an export folder: every file the export made (a link, which
        gives back no space and leaves the stored file alone; or a copy, which
        does), then the folder. Anything in the folder that the export didn't
        make is yours and is left, with the folder. Only a folder with civex's
        marker is touched."""
        folder = Path(path)
        marker = _read_marker(folder)
        if marker is None:
            raise ValidationError(f"{folder} is not a folder a civex export made.")
        removed = freed = 0
        for rel, entry in marker.items():
            target = _inside(folder, rel)
            if target is None:
                continue  # a path that leads out of the folder: never followed
            try:
                file_modes.remove(target)  # a link goes, never what it points at
            except FileNotFoundError:
                continue
            removed += 1
            if entry["how"] in ("copied", GENERATED):
                freed += entry["size"]
            _prune_empty(folder, target.parent)
        (folder / MARKER).unlink(missing_ok=True)
        (folder / MISSING_NOTE).unlink(missing_ok=True)
        try:
            kept = sum(1 for _ in folder.rglob("*") if not _.is_dir())
        except OSError:
            kept = 0
        removed_folder = False
        if kept == 0:
            _prune_empty(folder.parent, folder)
            removed_folder = not folder.exists()
        return RemoveResult(str(folder), removed, freed, kept, removed_folder)

    # -- the files of a selection, by place (the Files tab) -----------------

    def _record_set(self, selection: FileSelection) -> RecordSet:
        """The records a selection means, as a set the database works out
        (the same reading as `_select_records`, which loads them)."""
        allowed = list(selection.schemas) if selection.schemas else None
        if selection.record_ids is not None:
            return RecordSet(
                ids=list(selection.record_ids), below=selection.below, kinds=allowed
            )
        query = selection.query
        narrowed = bool(query.where or query.search)
        ids: list[str] = []
        below = selection.below
        # The kinds a record beneath the chosen ones can be: None = any.
        beneath: list[str] | None = None
        if query.within and not query.schema:
            anchor = self._records.get(query.within)
            beneath = [
                d.name
                for d, _ in self._schemas.descendants(
                    self._schemas.get(anchor.schema_name)
                )
            ]
            ids = [str(anchor.id)]
            queries = [
                query.for_kind(n) for n in beneath if allowed is None or n in allowed
            ]
            # Every kind beneath the record is asked already: looking beneath
            # what they list finds nothing more (unless a search or a term
            # narrowed them, which their own children need not match).
            below = below and narrowed
        elif allowed and not query.schema:
            queries = [query.for_kind(n) for n in allowed]
            beneath = list(
                dict.fromkeys(
                    d.name
                    for n in allowed
                    for d, _ in self._schemas.descendants(self._schemas.get(n))
                )
            )
        else:
            queries = [query]
            if selection.with_within and query.within and query.schema:
                ids = [str(self._records.get(query.within).id)]
            if query.schema:
                beneath = [
                    d.name
                    for d, _ in self._schemas.descendants(
                        self._schemas.get(query.schema)
                    )
                ]
            elif not (
                narrowed or query.filter_tree or query.parent_record_id or query.within
            ):
                # A whole collection (or project): everything beneath its
                # records is among them.
                below = False
        listed = None
        if below and query.filter_tree:
            kinds = (
                beneath
                if beneath is not None
                else [s.name for s in self._schemas.list_all()]
            )
            listed = [query.for_kind(k) for k in kinds]
        return RecordSet(
            queries=queries, ids=ids, below=below, listed=listed, kinds=allowed
        )

    def _held(
        self, selection: FileSelection, name: str | None = None
    ) -> list[tuple[FileItem, bool, tuple[Any, Any, Any]]]:
        """Every file the selection's records hold, of every kind, from the
        database alone (`RecordService.held_files`): one statement however
        many records, and no drive asked where a file is (a drive is asked
        once whether it can be used). Each is a `FileItem` not yet named (no
        path, no record name, the file's name as it was added: `_named`
        names the few that are shown), whether `name` found it, and where it
        sorts ((its record's time, its record, its collection) as kept)."""
        if selection.layout not in LAYOUTS:
            raise ValidationError(f"layout must be one of: {', '.join(LAYOUTS)}")
        held = self._records.held_files(
            self._record_set(selection), (name or "").strip() or None
        )
        following = self._records.files_from_server()
        order = {v: n for n, v in enumerate(self._store.volume_names())}
        status = _memo(self._store.volume_status)
        ids: dict[Any, str] = {}
        waiting, waiting_fix = (
            "Not downloaded to this computer yet.",
            "Opening or exporting it downloads it from the server.",
        )
        lost, lost_fix = not_on_server_yet(None)
        # Records a device sent lately whose file is on no drive here: that
        # file is arriving (its device is still uploading), not missing.
        arriving: set[str] = set()
        if not following:
            owners = {
                uuid.UUID(record_key(h.record_id))
                for h in held
                if h.volume is None and not h.stored_on
            }
            if owners:
                arriving = {str(i) for i in self._records.recently_received(owners)}
        out: list[tuple[FileItem, bool, tuple[Any, Any, Any]]] = []
        for h in held:
            record_id = ids.get(h.record_id)
            if record_id is None:
                record_id = ids[h.record_id] = record_key(h.record_id)
            volume = h.volume
            if volume is None and h.stored_on:
                known = sorted(
                    (v for v in h.stored_on if v in order), key=order.__getitem__
                )
                volume = next(
                    (v for v in known if status(v).reachable),
                    known[0] if known else None,
                )
            if volume is not None:
                st = status(volume)
                item = FileItem(
                    "",
                    h.sha256,
                    h.filename,
                    h.size,
                    record_id,
                    "",
                    h.field,
                    volume,
                    st.state,
                    st.reachable,
                    st.reason,
                    st.fix,
                    None,
                    h.on_server if following else None,
                )
            elif following and h.server_lacks and not h.on_server:
                item = FileItem(
                    "",
                    h.sha256,
                    h.filename,
                    h.size,
                    record_id,
                    "",
                    h.field,
                    None,
                    "absent",
                    False,
                    lost,
                    lost_fix,
                    None,
                    False,
                )
            elif following:
                item = FileItem(
                    "",
                    h.sha256,
                    h.filename,
                    h.size,
                    record_id,
                    "",
                    h.field,
                    None,
                    "remote",
                    False,
                    waiting,
                    waiting_fix,
                    None,
                    h.on_server,
                )
            elif record_id in arriving:
                item = FileItem(
                    "",
                    h.sha256,
                    h.filename,
                    h.size,
                    record_id,
                    "",
                    h.field,
                    None,
                    "arriving",
                    False,
                    "Uploading: the computer that added it is still sending it.",
                )
            else:
                item = FileItem(
                    "", h.sha256, h.filename, h.size, record_id, "", h.field
                )
            out.append((item, h.found, (h.created_at, h.record_id, h.dataset_id)))
        return out

    def chosen(
        self,
        selection: FileSelection,
        place: str | None = None,
        name: str | None = None,
        shas: list[str] | None = None,
        used_by: list[int] | None = None,
        progress: Progress | None = None,
        server: str | None = None,
    ) -> list[FileItem]:
        """The files a person has picked: a selection's files, narrowed to its
        kinds of file (`selection.fields`), a place (`in_place`), a name (the
        name a file was added under, or its record or one above it found as a
        search of records finds them), ticked files (`shas`: a file with
        every use of it listed here; records outside the selection that use
        it are not picked), how many live records use a file (`used_by`, see
        `use_counts`), and whether the server has it (`server`: `sent` or
        `unsent`, see `server_state`). The one rule behind the file list and
        every action on it, so what is listed is what is acted on.

        Answered from the database alone (`_held`), so it costs the same
        short while whatever the selection's size; the files come without a
        path or a record's name, which no action on them needs."""
        if progress:
            progress.phase("Finding files")
        return self._chosen(
            self._held(selection, name), selection, place, shas, server, used_by
        )

    def _chosen(
        self,
        held: list[tuple[FileItem, bool, tuple[Any, Any, Any]]],
        selection: FileSelection,
        place: str | None,
        shas: list[str] | None,
        server: str | None,
        used_by: list[int] | None = None,
    ) -> list[FileItem]:
        if server is not None and server not in SERVER_STATES:
            raise ValidationError(f"server must be one of: {', '.join(SERVER_STATES)}")
        kinds = set(selection.fields) if selection.fields else None
        wanted = set(shas) if shas is not None else None
        items = [
            i
            for i, found, _ in held
            if found
            and (kinds is None or i.field in kinds)
            and (place is None or in_place(i, place))
            and (server is None or server_state(i) == server)
            and (wanted is None or i.sha256 in wanted)
        ]
        if used_by:
            counts = self.use_counts(items)
            items = [i for i in items if counts[copy_key(i)] in set(used_by)]
        return items

    def use_counts(self, items: list[FileItem]) -> dict[str, int]:
        """How many live records use each of these files as stored (by
        `copy_key`: the copy they point at), anywhere (at least the records
        among these that do). A duplicate on another drive is another file.
        One statement, whatever the number of files."""
        uses: dict[str, list[FileItem]] = {}
        for i in items:
            uses.setdefault(copy_key(i), []).append(i)
        return self._use_counts(uses)

    def _use_counts(self, uses: dict[str, list[FileItem]]) -> dict[str, int]:
        users = self._records.shared_copies()
        out: dict[str, int] = {}
        for key, found in uses.items():
            here = 1 if len(found) == 1 else len({i.record_id for i in found})
            out[key] = max(users.get(_key_parts(key), 0), here)
        return out

    def listing(
        self,
        selection: FileSelection,
        place: str | None = None,
        name: str | None = None,
        sort: str = "path",
        offset: int = 0,
        limit: int = 100,
        used_by: list[int] | None = None,
        server: str | None = None,
    ) -> FileListing:
        """A page of a selection's files, one row per file as it is stored (a
        file several records use is one row, with `uses` naming them), narrowed
        like `chosen`. With where the files of the kinds chosen are (`summary`,
        before narrowing by place, so the places a person can pick stay in
        view) and how many of each kind the selection holds (`kinds`, before
        narrowing by kind); every count is of files, not of uses. `used_by`
        keeps the files used by exactly so many live records (anywhere), and
        `sharing` counts the files by that.

        The counts and the order come from the database alone (`_held`);
        only the page's rows are named (`_named`: their records, the records
        above them, the names their templates give). So `sort` orders by what
        is stored: `path` and `record` by the order records are listed in
        (when each was added), `name` by the name a file was added under,
        `size`, `place`; a leading "-" reverses it."""
        if server is not None and server not in SERVER_STATES:
            raise ValidationError(f"server must be one of: {', '.join(SERVER_STATES)}")
        held = self._held(selection, name)
        chosen_kinds = set(selection.fields) if selection.fields else None
        every = [i for i, _, _ in held]
        of_kind = (
            [i for i in every if i.field in chosen_kinds] if chosen_kinds else every
        )
        # One pass: the files that are listed (narrowed as `_chosen` narrows
        # them), gathered by copy, and where each copy sorts (by the first of
        # the records that use it).
        uses: dict[str, list[FileItem]] = {}
        first: dict[str, tuple[Any, ...]] = {}
        for item, found, (made, record, _) in held:
            if not (
                found
                and (chosen_kinds is None or item.field in chosen_kinds)
                and (place is None or in_place(item, place))
                and (server is None or server_state(item) == server)
            ):
                continue
            key = copy_key(item)
            at = (made, record, item.filename.casefold(), item.sha256)
            if key not in uses:
                uses[key] = [item]
                first[key] = (*at, item)
                continue
            uses[key].append(item)
            if at < first[key][:4]:
                first[key] = (*at, item)
        used = self._use_counts(uses)
        counts = Counter(used.values())
        rows = [key for key in uses if not used_by or used[key] in set(used_by)]
        key_name, reverse = sort.lstrip("-"), sort.startswith("-")
        order: dict[str, Callable[[str], Any]] = {
            "path": lambda k: first[k][:4],
            "record": lambda k: first[k][:4],
            "name": lambda k: (first[k][2], *first[k][:2], first[k][3]),
            "size": lambda k: (first[k][4].size, *first[k][:4]),
            "place": lambda k: (place_of(first[k][4])[0].casefold(), *first[k][:4]),
        }
        if key_name not in order:
            raise ValidationError(f"sort must be one of: {', '.join(order)}")
        rows.sort(key=order[key_name], reverse=reverse)
        shown = rows[offset : offset + limit]
        named = self._named(
            selection,
            {key: uses[key] for key in shown},
            len({at[2] for _, _, at in held}) > 1,
        )
        return FileListing(
            total=len(rows),
            summary=_places(_one_each(of_kind)),
            server=_by_server(of_kind),
            items=[named[key][0] for key in shown],
            kinds=_kinds(every),
            uses=named,
            others={
                key: used[key] - len({u.record_id for u in uses[key]}) for key in shown
            },
            sharing=[{"records": n, "files": counts[n]} for n in sorted(counts)],
        )

    def _named(
        self,
        selection: FileSelection,
        uses: dict[str, list[FileItem]],
        several_collections: bool,
    ) -> dict[str, list[FileItem]]:
        """The same files as they are shown: each with its path (the records
        above it), its record's name, the name its template gives it and why
        it can't be reached when it can't. `uses` is the files to name, by
        copy; only their records are read (a plan of just those, so the one
        path rule names them), which is why a page costs the same whatever it
        is a page of. Each copy's uses come back in path order."""
        wanted = {
            (i.record_id, i.field, i.sha256) for found in uses.values() for i in found
        }
        if not wanted:
            return {}
        plan = self._plan(
            FileSelection(
                record_ids=sorted({record for record, _, _ in wanted}),
                base=selection.base or selection.query.within,
                layout=selection.layout,
            ),
            False,
            None,
            lead_with_collection=several_collections,
        )
        found: dict[tuple[str, str, str], list[FileItem]] = {}
        for item in plan.items:
            found.setdefault((item.record_id, item.field, item.sha256), []).append(item)
        out: dict[str, list[FileItem]] = {}
        for key, items in uses.items():
            named = [
                n
                for spot in dict.fromkeys(
                    (i.record_id, i.field, i.sha256) for i in items
                )
                for n in found.get(spot, [])
            ]
            # A record changed since it was counted: shown as it was read.
            out[key] = sorted(named or items, key=lambda i: i.path.casefold())
        return out

    def plan_move(self, items: list[FileItem], volume: str) -> MovePlan:
        """What moving these files onto `volume` would do. The picked records
        point at the drive's copy afterwards; each file is carried there unless
        a copy is there already (then nothing is copied: they share it), and
        the copy it came from stays while records not picked point at it
        (copied, not moved), else it is freed. Files only on the server come
        straight there. The transfer's own steps (`plan_steps`), so the move
        dialog's preview and the move itself can't disagree. Unreachable and
        missing files can't move and are left out."""
        return self._move(items, volume)[0]

    def _move(
        self,
        items: list[FileItem],
        volume: str,
        progress: Progress | None = None,
    ) -> tuple[MovePlan, list[str]]:
        """`plan_move`'s plan and `shas_to_move`'s content from one pass (the
        transfer's steps cost a lookup per batch of files)."""
        if volume not in self._drives().volume_names():
            raise NotFoundError(f"There is no drive called '{volume}'.")
        size = {i.sha256: i.size for i in items}
        on_drives = sorted({i.sha256 for i in items if place_of(i)[1] == "drive"})
        remote = {i.sha256 for i in items if place_of(i)[1] == "server"}
        plan = MovePlan(files=0, bytes=0, from_server=len(remote), already_there=0)
        moving: list[str] = []
        records = sorted({i.record_id for i in items})
        if progress:
            progress.phase("Finding files", len(on_drives))
        for n, step in enumerate(self._steps(on_drives, volume, records), 1):
            plan.freed_bytes += len(step.drop) * size[step.sha256]
            if step.step == STEP_THERE:
                plan.already_there += 1
                if step.rows or step.drop:
                    plan.repointed += 1
                    moving.append(step.sha256)
            elif step.step in (STEP_MOVE, STEP_COPY):
                plan.files += 1
                plan.bytes += size[step.sha256]
                moving.append(step.sha256)
                if step.step == STEP_COPY:
                    plan.copied += 1
            if progress and n % 200 == 0:
                progress.advance(n)
        return plan, moving

    def _steps(
        self, shas: list[str], volume: str, records: list[str]
    ) -> Iterator[Step]:
        """What gathering these records' files onto `volume` does with each
        (the transfer's own rule)."""
        if self.refs is None:
            return iter(())
        return plan_steps(
            self._drives(), self.refs, self.move_spec(shas, volume, records)
        )

    @staticmethod
    def move_spec(shas: list[str], volume: str, records: list[str]) -> TransferSpec:
        """The transfer that moves these records' copies of these files onto
        `volume` (only their pointers move; others' copies stay)."""
        return TransferSpec(
            kind=KIND_FILES,
            targets=[volume],
            shas=shas,
            record_ids=records,
            freeze_sources=False,
        )

    def to_move(
        self,
        items: list[FileItem],
        volume: str,
        progress: Progress | None = None,
    ) -> tuple[list[str], int, MovePlan]:
        """Get these files onto `volume`, as `plan_move` says: those only on
        the server are downloaded straight onto it; returns the content a
        move has to carry from other drives (each once), how many were
        downloaded there, and the plan."""
        plan, moving = self._move(items, volume, progress)
        remote = [i for i in items if place_of(i)[1] == "server"]
        fetched = self._fetch(
            [i.sha256 for i in remote], progress, volume, _sizes(remote)
        )
        return moving, fetched.fetched if fetched else 0, plan

    def shas_to_move(self, items: list[FileItem], volume: str) -> list[str]:
        """The content a move has to carry onto `volume` from other drives:
        each file not there yet, once. Downloads nothing."""
        return self._move(items, volume)[1]

    def download(
        self, items: list[FileItem], progress: Progress | None = None
    ) -> dict[str, Any]:
        """Fetch the files among these that aren't on this computer. Says how
        many came, how many of the listed rows that covers (records that share
        a file share its download), and, for any the server hasn't got either,
        where they still are, grouped by that."""
        remote = [i for i in items if place_of(i)[1] == "server"]
        wanted = list(dict.fromkeys(i.sha256 for i in remote))
        report = self._fetch(wanted, progress, sizes=_sizes(remote))
        here = self._store.locate_volumes(wanted)
        absent = report.absent if report else []
        why = self.why_not_here(absent) if (absent and self.why_not_here) else {}
        groups: dict[tuple[str, str], int] = {}
        for sha in absent:
            key = why.get(sha, not_on_server_yet(None))
            groups[key] = groups.get(key, 0) + 1
        return {
            "fetched": report.fetched if report else 0,
            "listed": sum(1 for i in items if here.get(i.sha256)),
            "absent": len(absent),
            "absent_where": [
                {"reason": r, "fix": f, "files": n} for (r, f), n in groups.items()
            ],
        }

    def free_up(self, items: list[FileItem], dry_run: bool = True) -> Any:
        """Remove this computer's copies of these files, where the server holds
        them (see `SyncService.free_up_files` for what is kept and why)."""
        if not self.free_files:
            raise ValidationError(
                "This project doesn't follow a server, so its files have nowhere "
                "else to come from: they can't be removed to free space."
            )
        here = list(dict.fromkeys(i.sha256 for i in items if place_of(i)[1] == "drive"))
        return self.free_files(here, dry_run)

    def missing_note(self, plan: FilePlan) -> str | None:
        """The text for a zip's MISSING.txt: the files that couldn't be reached
        and why. None when everything could."""
        gone = [i for i in plan.items if not i.available]
        if not gone:
            return None
        return (
            "These files could not be reached when this zip was made:\n\n"
            + "\n".join(f"{i.path}: {i.reason or 'not available'}" for i in gone)
            + "\n"
        )

    def zip_entries(self, plan: FilePlan) -> list[tuple[str, FileRef]]:
        """(path in the archive, blob) for each file that can be reached -- the
        same paths as an export, for someone who can't see this machine's disk."""
        return [
            (i.path, FileRef(sha256=i.sha256, filename=i.filename, size=i.size))
            for i in plan.items
            if i.available
        ]


# --- helpers ---------------------------------------------------------------


def _memo(fn: Callable[..., Any]) -> Callable[..., Any]:
    """`fn` remembering its answers for the arguments it has seen, for the length
    of one operation."""
    seen: dict[Any, Any] = {}

    def call(*args: Any) -> Any:
        if args not in seen:
            seen[args] = fn(*args)
        return seen[args]

    return call


@dataclasses.dataclass
class _Draft:
    """A table before it has a folder and a name: its spec, the kind of its rows,
    the record whose folder it goes in (None = the top) and the rows."""

    spec: table_rules.TableSpec
    kind: str
    holder: RecordDTO | None
    members: list[RecordDTO]


def _pool(
    kind: str,
    records: list[RecordDTO],
    trails: dict[Any, list[RecordDTO]],
    base_id: str | None,
) -> list[RecordDTO]:
    """The records of `kind` an export has to hand: the ones it takes, then the
    ones above them (only from the base down, when there is one), each once, in
    the order met."""
    found: dict[Any, RecordDTO] = {}
    for r in records:
        if r.schema_name == kind:
            found.setdefault(r.id, r)
    for r in records:
        above = trails.get(r.id, [])
        if base_id is not None:
            ids = [str(a.id) for a in above]
            above = above[ids.index(base_id) :] if base_id in ids else []
        for a in above:
            if a.schema_name == kind:
                found.setdefault(a.id, a)
    return list(found.values())


def _record_column(record: RecordDTO, column: str) -> Any:
    if column == "id":
        return str(record.id)
    if column == "schema":
        return record.schema_name
    if column == "parent_record_id":
        return str(record.parent_record_id) if record.parent_record_id else None
    return getattr(record, column).isoformat()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _named(value: Any, names: dict[str, str]) -> Any:
    """A reference value (an id, or a list of them) as the records' names; an
    id whose record has no name (or is gone) stays the id."""
    if isinstance(value, list):
        return [names.get(v, v) if isinstance(v, str) else v for v in value]
    return names.get(value, value) if isinstance(value, str) else value


def _pandas() -> Any:
    """pandas, imported only when a DataFrame is asked for (it is slow to
    import, and nothing else here needs it)."""
    try:
        import pandas
    except ImportError as exc:
        raise ImportError(
            "A DataFrame needs pandas, which isn't installed in this Python: "
            "`pip install pandas` (or `typed_rows`, which needs nothing)."
        ) from exc
    return pandas


# A civex type -> the pandas dtype its column is given.
_PANDAS_DTYPES = {
    "integer": "Int64",
    "float": "float64",
    "boolean": "boolean",
    "enum": "category",
    "string": "string",
    "longtext": "string",
    "url": "string",
    "file": "string",
    "reference": "string",
}


def _pandas_column(
    pd: Any, values: list[Any], dtype: str, restrictions: dict[str, Any]
) -> Any:
    """One column as a pandas Series of its type. A column holding a value
    that isn't of its type (a legacy row) is left as plain objects, never
    coerced to blank."""
    series = pd.Series(values, dtype=object)
    try:
        if dtype == "datetime":
            return pd.to_datetime(series, utc=True)
        if dtype == "date":
            if all(v is None or type(v).__name__ == "date" for v in values):
                return pd.to_datetime(series)
            return series.astype("string")
        if dtype in _PANDAS_DTYPES:
            return series.astype(_PANDAS_DTYPES[dtype])
    except (TypeError, ValueError, OverflowError):
        return series
    return series


def _display_filename(value: Any) -> Any:
    """A file cell's raw value(s) as the file's name: a table says which file,
    never holds the file's metadata."""
    if isinstance(value, dict):
        return value.get("resolved_filename") or value.get("filename")
    if isinstance(value, list):
        return [_display_filename(v) for v in value if isinstance(v, dict)]
    return value


def _record_name(record: RecordDTO) -> str:
    return record.natural_name or f"{record.schema_name} {str(record.id)[:8]}"


def _file_name(ref: dict[str, Any]) -> str:
    return (
        ref.get("resolved_filename") or ref.get("filename") or str(ref["sha256"])[:12]
    )


def _gone(item: FileItem) -> FileItem:
    return dataclasses.replace(item, available=False, reason=_NOT_ON_DISK)


def _unavailable_groups(items: list[FileItem]) -> list[UnavailableGroup]:
    groups: dict[tuple[str | None, str, str, str], UnavailableGroup] = {}
    for item in items:
        if item.available or item.state == "remote":  # to download, not lost
            continue
        reason = item.reason or (
            "" if item.volume else "Not stored on any drive this project knows."
        )
        key = (item.volume, item.state, reason, item.fix)
        group = groups.setdefault(
            key, UnavailableGroup(item.volume, item.state, reason, item.fix, 0, 0, [])
        )
        group.files += 1
        group.bytes += item.size
        if (
            item.record_name
            and item.record_name not in group.records
            and len(group.records) < _SHOWN_RECORDS
        ):
            group.records.append(item.record_name)
    return sorted(groups.values(), key=lambda g: (-g.files, g.volume or ""))


def _place(source: Path, target: Path, mode: str) -> str:
    """Put one file at `target`: "hardlinked" (the stored file under another
    name, made read-only so it can't be edited by mistake; same drive only) or
    "copied" (written beside the target and renamed into place, so a
    half-written file never appears). A link that can't be made after all (the
    drive's limit on links to one file) is a copy instead."""
    file_modes.remove(target, missing_ok=True)
    if mode == "link":
        try:
            os.link(source, target)
        except FileNotFoundError:
            raise
        except OSError:
            pass
        else:
            file_modes.make_read_only(target)
            return "hardlinked"
    part = target.with_name(target.name + ".part")
    try:
        shutil.copyfile(source, part)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return "copied"


def _size(n: int) -> str:
    value = float(n)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} bytes"


def _present(folder: Path) -> set[str]:
    """Names in `folder` that lead to a file (a link whose target is gone does
    not count), from one directory read."""
    try:
        with os.scandir(folder) as entries:
            return {e.name for e in entries if not e.is_symlink() or _alive(e)}
    except OSError:
        return set()


def _alive(entry: os.DirEntry[str]) -> bool:
    try:
        entry.stat()
        return True
    except OSError:
        return False


def _read_marker(dest: Path) -> dict[str, dict[str, Any]] | None:
    """What an export recorded about its folder: path -> {sha, how, size}; None
    if `dest` isn't an export folder. Reads the first format too, which kept
    only each file's hash."""
    try:
        files = json.loads((dest / MARKER).read_text("utf-8"))["files"]
        out: dict[str, dict[str, Any]] = {}
        for path, entry in files.items():
            if isinstance(entry, dict):
                out[str(path)] = {
                    "sha": str(entry.get("sha", "")),
                    "how": str(entry.get("how", "")),
                    "size": int(entry.get("size") or 0),
                }
            else:
                out[str(path)] = {"sha": str(entry), "how": "", "size": 0}
        return out
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return None


def _zulu(moment: datetime) -> str:
    """A moment in UTC as `2026-10-05T19:20:00Z`: whole seconds, the Z that says
    it is Zulu time, nothing to misread as a local time."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_marker(dest: Path, files: dict[str, dict[str, Any]], mode: str) -> None:
    body = {
        "made_by": "civex",
        # Which civex wrote it, so a folder found later says what made it.
        "civex_version": __version__,
        # The layout of this file, for whatever reads it next.
        "format": MARKER_FORMAT,
        "mode": mode,
        "updated": _zulu(datetime.now(timezone.utc)),
        "files": files,
    }
    tmp = dest / (MARKER + ".tmp")
    tmp.write_text(json.dumps(body, indent=1), "utf-8")
    os.replace(tmp, dest / MARKER)


def _describe(folder: Path, location: str) -> ExportInfo | None:
    """One export folder as a listing row, from its marker alone."""
    files = _read_marker(folder)
    if files is None:
        return None
    try:
        updated = json.loads((folder / MARKER).read_text("utf-8")).get("updated")
    except (OSError, ValueError):
        updated = None
    known = [e for e in files.values() if e["how"]]
    complete = len(known) == len(files)
    return ExportInfo(
        name=folder.name,
        location=location,
        path=str(folder),
        files=len(files),
        bytes_on_disk=(
            sum(e["size"] for e in known if e["how"] in ("copied", GENERATED))
            if complete
            else None
        ),
        linked=sum(1 for e in known if e["how"] == "hardlinked") if complete else None,
        copied=sum(1 for e in known if e["how"] == "copied") if complete else None,
        updated=updated,
    )


def _write_missing_note(dest: Path, missing: list[FileItem]) -> None:
    note = dest / MISSING_NOTE
    if not missing:
        note.unlink(missing_ok=True)
        return
    lines = [
        "This folder is incomplete. These files could not be reached when it was made:",
        "",
    ]
    for item in missing:
        why = item.reason or "not available"
        where = f" [{item.volume}]" if item.volume else ""
        fix = f" -- {item.fix}" if item.fix else ""
        lines.append(f"{item.path}{where}: {why}{fix}")
    lines += ["", "Run the export again once they are reachable to add them."]
    note.write_text("\n".join(lines) + "\n", "utf-8")


def _inside(folder: Path, rel: str) -> Path | None:
    """`rel` below `folder`, or None if it would lead outside it. The marker is
    a file anyone can edit, so removal never trusts a path in it."""
    parts = rel.split("/")
    if rel.startswith("/") or any(p in ("", "..") for p in parts) or ":" in parts[0]:
        return None
    return folder.joinpath(*parts)


def _prune_empty(stop: Path, start: Path) -> None:
    """Remove `start`, then each folder above it, for as long as they are empty
    and still below `stop` (which is never removed)."""
    current = start
    while stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _remove(dest: Path, path: str) -> None:
    """Delete one exported file, then any folders it leaves empty (never `dest`)."""
    target = _inside(dest, path)
    if target is None:
        return
    file_modes.remove(target, missing_ok=True)
    _prune_empty(dest, target.parent)


def _places(items: list[FileItem]) -> list[PlaceSummary]:
    """Every file of a selection by place, readable drives first, then
    unreachable drives, the server, arriving, and missing (biggest first within each)."""
    out: dict[tuple[str, str], PlaceSummary] = {}
    for item in items:
        place, kind = place_of(item)
        row = out.setdefault(
            (place, kind),
            PlaceSummary(
                place,
                kind,
                0,
                0,
                item.reason if kind == "unreachable" else "",
                item.fix if kind == "unreachable" else "",
            ),
        )
        row.files += 1
        row.bytes += item.size
    rank = {"drive": 0, "unreachable": 1, "server": 2, "arriving": 3, "missing": 4}
    return sorted(out.values(), key=lambda r: (rank[r.kind], -r.bytes, r.place))


def _by_server(items: list[FileItem]) -> list[dict[str, Any]]:
    """Every file of a selection by whether the server has it (`server_state`;
    counted by content, which the server holds once), on the server first.
    Empty when this project follows no server."""
    out: dict[str, dict[str, Any]] = {}
    for item in {i.sha256: i for i in items}.values():
        state = server_state(item)
        if state is None:
            continue
        row = out.setdefault(state, {"state": state, "files": 0, "bytes": 0})
        row["files"] += 1
        row["bytes"] += item.size
    return [out[k] for k in (PLACE_SENT, PLACE_UNSENT) if k in out]


def _one_each(items: list[FileItem]) -> list[FileItem]:
    """One item per file as stored (`copy_key`): however many records use a
    copy, it is one file in a count and its bytes are on disk once."""
    return list({copy_key(i): i for i in reversed(items)}.values())


def _key_parts(key: str) -> tuple[str, str | None]:
    sha, _, volume = key.partition("@")
    return sha, volume or None


def _kinds(items: list[FileItem]) -> list[dict[str, Any]]:
    """How many files of each kind (file field) a selection holds, most
    first: the choices of the list's "kind of file" pick. A file counts once
    per kind however many records use it."""
    out: dict[str, dict[str, Any]] = {}
    for item in {(i.field, i.sha256): i for i in items}.values():
        row = out.setdefault(item.field, {"field": item.field, "files": 0, "bytes": 0})
        row["files"] += 1
        row["bytes"] += item.size
    return sorted(out.values(), key=lambda r: (-r["files"], r["field"]))


def _sizes(items: list[FileItem]) -> dict[str, int]:
    """Each file's size, as its records say, for how many bytes a download
    has to bring."""
    return {i.sha256: i.size for i in items}
