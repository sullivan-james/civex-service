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

import dataclasses
import json
import os
import posixpath
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from civex import __version__
from civex.domain.dtos import FileRef, RecordDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain import tables as table_rules
from civex.domain import templating
from civex.domain.naming import display_label
from civex.domain.file_access import (
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
    FilesScatteredError,
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
from civex.repositories.protocols import FileObjectStore
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
_NOT_ON_DISK = "The file is not on the drive where it should be."
_SHOWN_RECORDS = 10  # record names listed per unreachable group


class FileAccessService:
    def __init__(
        self,
        records: RecordService,
        schemas: SchemaService,
        store: FileObjectStore,
        civex_dir: Path,
    ) -> None:
        self._records = records
        self._schemas = schemas
        self._store = store
        self._civex_dir = civex_dir
        # Downloads files another device added (they are cited here but on no
        # drive here) from the authority, given their hashes and a callable told
        # how many have arrived; None when the project follows none. Injected
        # so this service doesn't know sync.
        self.fetch_missing: (
            Callable[[list[str], Callable[[int], None] | None], Any] | None
        ) = None
        # Removes this computer's copies of content the server holds (given the
        # hashes and whether only to count); None when the project follows no
        # server. Injected like `fetch_missing`.
        self.free_files: Callable[[list[str], bool], object] | None = None

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
        self._fetch(remote, progress)
        return _absent_now(self._plan(selection, with_sources, progress))

    def _fetch(self, shas: list[str], progress: Progress | None) -> Any:
        """Download these files from the server, as a stage of the work a
        person is watching (the same progress as the rest of it)."""
        shas = list(dict.fromkeys(shas))
        if not shas or not self.fetch_missing:
            return None
        if progress:
            progress.phase(
                f"Downloading {len(shas)} file{'s' if len(shas) != 1 else ''} "
                "from the server",
                len(shas),
            )
        return self.fetch_missing(shas, progress.advance if progress else None)

    def _plan(
        self,
        selection: FileSelection,
        with_sources: bool,
        progress: Progress | None,
    ) -> FilePlan:
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
        records = self._select_records(selection, progress)
        values: list[tuple[RecordDTO, str, dict[str, Any]]] = []
        if selection.files:
            if progress:
                progress.phase("Working out the folders")
            values, known = self._records.file_values(records, selection.fields)
            if selection.fields and not (known & set(selection.fields)):
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
                selection.query, schema=kind, filter_tree=None, where=[], search=None
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
        return self._store.path_on(item.sha256, item.volume)

    def _with_source(self, item: FileItem) -> FileItem:
        if not item.available or item.volume is None:
            return item
        path = self._source(item)
        try:
            path.stat()
        except OSError:
            return _gone(item)
        return dataclasses.replace(item, source=str(path))

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
            queries = [dataclasses.replace(query, schema=name) for name in below]
        elif allowed and not query.schema:
            # Several kinds, whole collection: each kind in turn.
            queries = [
                dataclasses.replace(query, schema=name)
                for name in selection.schemas or []
            ]
        else:
            queries = [query]
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
            if progress:
                progress.phase("Finding what is inside")
            beneath = self._records.beneath(
                found, (lambda n: progress.advance(n)) if progress else None
            )
            everything = [*found, *beneath]
        if allowed is not None:
            everything = [r for r in everything if r.schema_name in allowed]
        return everything

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
        try:
            root = self._store.volume_path(volume).resolve()
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
        if location not in self._store.volume_names():
            raise NotFoundError(f"There is no drive called '{location}'.")
        if self._in_project(location):
            return self._civex_dir / PROJECT_EXPORTS
        return self._store.volume_path(location) / VOLUME_EXPORTS

    def destination(self, location: str, name: str | None) -> Path:
        """The folder an export called `name` has at `location`. The same name
        gives the same folder, so opening a view again refreshes it instead of
        piling up copies."""
        return self.exports_root(location) / safe_segment(name, "files")

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
        """Export into civex's own exports folder. `link` puts it on the one
        drive that holds the files (refusing files scattered over several);
        `copy` puts real copies on `volume` (or in the project if none is
        named), wherever the files are. Both can be cleaned up with
        `list_exports` / `remove_export`."""
        if mode not in EXPORT_MODES:
            raise ValidationError(f"mode must be one of: {', '.join(EXPORT_MODES)}")
        plan = plan or self.plan(selection, progress=progress, fetch=True)
        if not plan.complete and not allow_partial:
            raise FilesUnavailableError(plan)
        if mode == "link":
            if plan.scattered:
                raise FilesScatteredError(plan)
            location = (
                self.location_of(plan.link_volume) if plan.link_volume else PROJECT
            )
        else:
            location = PROJECT if volume in (None, "", PROJECT) else volume
            if location not in (PROJECT, *self._store.volume_names()):
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

        Nothing is made, and an error says why, if: any file is out of reach and
        `allow_partial` is not set (`FilesUnavailableError`); for `link`, the
        files are on more than one drive (`FilesScatteredError`) or `dest` isn't
        somewhere a hard link to them can be made (`LinksNotPossibleError`); for
        `copy`, `dest` hasn't room. Running it again on the same folder brings it
        up to date: what is there is left, what is new is added, what is no longer
        selected is removed -- but only in a folder an earlier export made, never
        one that holds other files. A link *is* the stored file, so don't edit it
        in place; a copy is yours to change."""
        if mode not in EXPORT_MODES:
            raise ValidationError(f"mode must be one of: {', '.join(EXPORT_MODES)}")
        plan = plan or self.plan(selection, progress=progress, fetch=True)
        if not plan.complete and not allow_partial:
            raise FilesUnavailableError(plan)
        if mode == "link" and plan.scattered:
            raise FilesScatteredError(plan)

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
        want = "hardlinked" if mode == "link" else "copied"

        def in_place(item: FileItem) -> bool:
            entry = previous.get(item.path)
            return bool(entry and entry["sha"] == item.sha256 and entry["how"] == want)

        reachable = [i for i in plan.items if i.available and i.volume]
        if mode == "link" and reachable:
            self._probe_link(self._source(reachable[0]), dest)
        if mode == "copy":
            self._check_room(
                dest, location, sum(i.size for i in reachable if not in_place(i))
            )
        dest.mkdir(parents=True, exist_ok=True)

        result = ExportResult(dest=str(dest), location=location)
        kept: dict[str, dict[str, Any]] = {}
        handled = 0
        if progress:
            progress.phase(
                "Making the folder" if mode == "link" else "Copying the files",
                len(plan.items),
            )
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
                    how = _place(source, where / name, mode)
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

    def _probe_link(self, source: Path, dest: Path) -> None:
        """Whether a hard link to `source` can be made at `dest`, tried with a
        throwaway name in the nearest folder that exists, before anything is
        built. Fails with the reason a person can act on."""
        anchor = dest
        while not anchor.exists() and anchor != anchor.parent:
            anchor = anchor.parent
        probe = anchor / f".civex-link-probe-{os.getpid()}"
        try:
            os.link(source, probe)
        except FileNotFoundError:
            return  # the file itself is gone; the build reports that per file
        except OSError as e:
            raise LinksNotPossibleError(
                f"A linked folder can't be made at {dest}: {e.strerror or e}. "
                "Links need the folder to be on the same drive as the files, on a "
                "drive that supports them (not exFAT or FAT32). Copy the files "
                "to a drive instead."
            ) from e
        finally:
            probe.unlink(missing_ok=True)

    def _check_room(self, dest: Path, location: str | None, need: int) -> None:
        if need <= 0:
            return
        free: int | None
        if location and location != PROJECT and location in self._store.volume_names():
            free = self._store.room_on(location)
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
        roots = [(PROJECT, self._civex_dir / PROJECT_EXPORTS)]
        for volume in self._store.volume_names():
            if (
                not self._in_project(volume)
                and self._store.volume_status(volume).reachable
            ):
                roots.append((volume, self._store.volume_path(volume) / VOLUME_EXPORTS))
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
                target.unlink()  # a link is removed, never what it points at
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

    def chosen(
        self,
        selection: FileSelection,
        place: str | None = None,
        name: str | None = None,
        shas: list[str] | None = None,
    ) -> tuple[FilePlan, list[FileItem]]:
        """The files a person has picked: a selection's files, narrowed to a
        place (`in_place`), a name (in the file's or its record's), and ticked
        content (`shas`). The one rule behind the Files tab's list and every
        action on it, so what is listed is what is acted on."""
        plan = self.plan(selection)
        needle = (name or "").strip().casefold()
        wanted = set(shas) if shas is not None else None
        items = [
            i
            for i in plan.items
            if (place is None or in_place(i, place))
            and (
                not needle
                or needle in i.filename.casefold()
                or needle in i.record_name.casefold()
            )
            and (wanted is None or i.sha256 in wanted)
        ]
        return plan, items

    def listing(
        self,
        selection: FileSelection,
        place: str | None = None,
        name: str | None = None,
        sort: str = "path",
        offset: int = 0,
        limit: int = 100,
    ) -> FileListing:
        """A page of a selection's files, narrowed like `chosen`, with where all
        of the selection's files are (`summary`, before narrowing, so the
        places a person can pick stay in view). `sort`: path, name, size,
        record or place; a leading "-" reverses it."""
        plan, items = self.chosen(selection, place, name)
        key, reverse = sort.lstrip("-"), sort.startswith("-")
        order: dict[str, Callable[[FileItem], Any]] = {
            "path": lambda i: i.path.casefold(),
            "name": lambda i: i.filename.casefold(),
            "size": lambda i: i.size,
            "record": lambda i: (i.record_name.casefold(), i.path.casefold()),
            "place": lambda i: (place_of(i)[0].casefold(), i.path.casefold()),
        }
        if key not in order:
            raise ValidationError(f"sort must be one of: {', '.join(order)}")
        items.sort(key=order[key], reverse=reverse)
        return FileListing(
            total=len(items),
            summary=_places(plan.items),
            items=items[offset : offset + limit],
        )

    def to_move(
        self, items: list[FileItem], volume: str, progress: Progress | None = None
    ) -> list[str]:
        """The content that has to move for these files to be on `volume`: each
        not there yet, once; a file only on the server is downloaded first (it
        then moves like any other). Unreachable and missing files can't move
        and are left out (the plan the caller showed already said so)."""
        if volume not in self._store.volume_names():
            raise NotFoundError(f"There is no drive called '{volume}'.")
        movable = [i for i in items if place_of(i)[1] in ("drive", "server")]
        self._fetch([i.sha256 for i in movable if place_of(i)[1] == "server"], progress)
        located = self._store.locate_volumes(i.sha256 for i in movable)
        return [sha for sha, on in located.items() if on and on != volume]

    def download(self, items: list[FileItem], progress: Progress | None = None) -> Any:
        """Fetch the files among these that are only on the server."""
        return self._fetch(
            [i.sha256 for i in items if place_of(i)[1] == "server"], progress
        )

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
    return getattr(record, column).isoformat()


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
            item.record_name not in group.records
            and len(group.records) < _SHOWN_RECORDS
        ):
            group.records.append(item.record_name)
    return sorted(groups.values(), key=lambda g: (-g.files, g.volume or ""))


def _place(source: Path, target: Path, mode: str) -> str:
    """Put one file at `target`: "hardlinked" (the stored file under another
    name; same drive only) or "copied" (written beside the target and renamed
    into place, so a half-written file never appears)."""
    target.unlink(missing_ok=True)
    if mode == "link":
        os.link(source, target)
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
    target.unlink(missing_ok=True)
    _prune_empty(dest, target.parent)


def _places(items: list[FileItem]) -> list[PlaceSummary]:
    """Every file of a selection by place, readable drives first, then
    unreachable drives, the server, and missing (biggest first within each)."""
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
    rank = {"drive": 0, "unreachable": 1, "server": 2, "missing": 3}
    return sorted(out.values(), key=lambda r: (rank[r.kind], -r.bytes, r.place))


def _absent_now(plan: FilePlan) -> FilePlan:
    """A plan made after downloading what was only on the server: a file
    still not here is one the server hasn't got either, so it can't be reached
    (not "to download")."""
    gone = False
    for i, item in enumerate(plan.items):
        if item.state == "remote":
            gone = True
            plan.items[i] = dataclasses.replace(
                item,
                state="absent",
                available=False,
                reason="Not on the server yet: the device that added it hasn't sent it.",
                fix="It can be exported once that device has synced.",
            )
    if gone:
        plan.unavailable = _unavailable_groups(plan.items)
    return plan
