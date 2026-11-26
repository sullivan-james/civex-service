"""Bringing a spreadsheet in as records: the wizard's one backend.

There is no second import engine here. A spreadsheet is read by the Table step
(`civex.table@1`) and saved by the Save-as-records step (`civex.save_records@1`),
exactly as a workflow would run them; this service only works out what to ask
of them (which columns go in which fields, the fields to make first) and runs
them a part of the file at a time, so a large file is never held whole and the
caller can show progress. The file is one already stored (uploaded through the
files API), so nothing here names a path on this machine.

`run(..., check=True)` does everything a save does inside a SQL savepoint and
then forgets it: the counts and the rows it would skip are those the save will
give, because it is the same code on the same rows.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import shutil
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from civex_plugin_sdk.io_convert import to_invoke_form

from civex.domain import permissions
from civex.domain.exceptions import (
    NotFoundError,
    PluginExecutionError,
    ValidationError,
)
from civex.domain.naming import validate_name
from civex.domain.table_import import (
    IMPORT_DTYPES,
    ImportBatch,
    ImportColumn,
    ImportSheet,
    ImportSpec,
    derive_key,
    infer_dtype,
)
from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin
from civex.plugins.builtins.table import detect_delimiter
from civex.plugins.runtime import new_run_dir, runs_folder

if TYPE_CHECKING:
    from civex.context import AppContext

log = logging.getLogger(__name__)

#: Rows looked at to say what a column is and to show.
SAMPLE_ROWS = 1000
#: Rows shown in the preview.
SHOWN_ROWS = 10
#: Most rows one call handles.
MAX_BATCH = 5000
#: Seconds a step may take for one part.
STEP_TIMEOUT = 600.0
_EXCEL = (".xlsx", ".xlsm", ".xls")
#: Rows between the marks that let a batch start in the middle of the file.
_BLOCK = 1000
#: Rows handled at a time while a file is read through once.
_PASS_ROWS = 20_000
#: A read-through copy not used for this long is removed.
_COPY_SECONDS = 24 * 3600


class ImportService:
    def __init__(self) -> None:
        # Set by `build_context` once the context exists: the steps run on it.
        self._app_ctx: AppContext | None = None
        self._folder: Path | None = None

    @property
    def _ctx(self) -> AppContext:
        assert self._app_ctx is not None
        return self._app_ctx

    # -- reading -----------------------------------------------------------

    @contextmanager
    def _workspace(self) -> Iterator[None]:
        """A folder for the steps' tables and the file's copy, kept while a
        call runs (a table too large to pass inline is left in it) and removed
        after."""
        folder = new_run_dir()
        try:
            self._folder = folder
            yield
        finally:
            self._folder = None
            shutil.rmtree(folder, ignore_errors=True)

    def _workflow_ctx(self) -> WorkflowContext:
        # Work for no one record: the rows go at the top of a collection.
        return WorkflowContext(
            record=None, dataset=None, _app_ctx=self._ctx, run_dir=self._folder
        )

    def _file(self, sha256: str, filename: str) -> dict[str, Any]:
        self._ctx.file_svc.check_readable(sha256)
        size = self._ctx.file_svc.size_of(sha256)
        if size is None:
            raise NotFoundError("File not found")
        self._check_size(sha256, filename, size)
        return {"sha256": sha256, "filename": filename, "size": size}

    def _check_size(self, sha256: str, filename: str, size: int) -> None:
        """Refuse a file past the limits before anything parses it."""
        lim = self._ctx.config.import_
        if size > lim.max_file_mb * _MB:
            raise ValidationError(
                f"This file is {_mb(size)}; the most that can be brought in is "
                f"{lim.max_file_mb} MB."
            )
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            return
        try:
            where = self._ctx.file_svc.local_path(sha256)
            source = (
                where
                if where is not None
                else io.BytesIO(self._ctx.file_svc.retrieve(sha256))
            )
            with zipfile.ZipFile(source) as book:
                members = book.infolist()
        except Exception as e:  # not a zip, however it fails
            raise ValidationError(
                f"'{filename}' could not be opened as a spreadsheet: {e}"
            ) from e
        unpacked = sum(m.file_size for m in members)
        packed = max(1, sum(m.compress_size for m in members))
        if unpacked > lim.max_unpacked_mb * _MB:
            raise ValidationError(
                f"This spreadsheet unpacks to {_mb(unpacked)}; the most that "
                f"can be brought in is {lim.max_unpacked_mb} MB."
            )
        if unpacked / packed > lim.max_ratio:
            raise ValidationError(
                "This spreadsheet is packed far tighter than a real one "
                f"(over {lim.max_ratio} times), so it is not read."
            )

    def _read(
        self,
        file: dict[str, Any],
        sheet: str | None,
        *,
        skip: int = 0,
        limit: int | None = None,
        only: list[str] | None = None,
    ) -> Any:
        step = _step("civex.table@1")
        config = step.config_model(
            as_text=True,
            sheet=sheet,
            skip_rows=skip,
            max_rows=limit,
            only_columns=only,
            delimiters=[",", "tab", ";"],
        )
        try:
            result = step.invoke(
                {"files": [file]}, config, self._workflow_ctx(), STEP_TIMEOUT
            )
        except PluginExecutionError as e:
            raise ValidationError(_plain(e)) from e
        return to_invoke_form("table", result.outputs["table"])

    def inspect(
        self, sha256: str, filename: str, sheet: str | None = None
    ) -> ImportSheet:
        """What the file holds: its sheets, columns with what each looks like,
        the first rows and how many rows there are."""
        with self._workspace():
            return self._inspect(sha256, filename, sheet)

    def _inspect(self, sha256: str, filename: str, sheet: str | None) -> ImportSheet:
        self._ctx.file_svc.check_readable(sha256)
        file = self._file(sha256, filename)
        sheets = self._sheets(sha256, filename)
        if sheets and sheet is None:
            sheet = sheets[0]
        if sheets and sheet not in sheets:
            raise ValidationError(f"There is no sheet '{sheet}' in this file.")
        head = self._read(file, sheet, limit=SAMPLE_ROWS)
        headings = [str(c) for c in head.columns]
        if not headings:
            raise ValidationError("There is nothing in this file to bring in.")
        self._check_columns(len(headings))
        taken: set[str] = set()
        columns = []
        for position, heading in enumerate(headings, start=1):
            blank_heading = heading.startswith("Unnamed:") or not heading.strip()
            values = head[heading].tolist()
            columns.append(
                ImportColumn(
                    heading=heading,
                    label=f"Column {position}" if blank_heading else heading,
                    key=derive_key("" if blank_heading else heading, taken, position),
                    dtype=infer_dtype(values),
                    blanks=sum(1 for v in values if str(v).strip() == ""),
                )
            )
        total = len(head)
        if total >= SAMPLE_ROWS:
            # Count the rest by passing over it, holding a part at a time.
            total = sum(len(rows) for rows in self._passes(file, sheet, count=True))
        return ImportSheet(
            filename=filename,
            sheets=sheets,
            sheet=sheet,
            columns=columns,
            rows=[
                [str(v) for v in row] for row in head.head(SHOWN_ROWS).values.tolist()
            ],
            total=total,
        )

    def _sheets(self, sha256: str, filename: str) -> list[str]:
        if not filename.lower().endswith(_EXCEL):
            return []
        import io

        import pandas as pd

        try:
            # From the stored file where it is, not a copy held in memory.
            where = self._ctx.file_svc.local_path(sha256)
            source = (
                where
                if where is not None
                else io.BytesIO(self._ctx.file_svc.retrieve(sha256))
            )
            with pd.ExcelFile(source) as book:
                return [str(n) for n in book.sheet_names]
        except Exception as e:  # a file that is no Excel file, however it fails
            raise ValidationError(
                f"'{filename}' could not be opened as a spreadsheet: {e}"
            ) from e

    # -- reading through once ----------------------------------------------

    def _check_columns(self, n: int) -> None:
        most = self._ctx.config.import_.max_columns
        if n > most:
            raise ValidationError(
                f"This file has {n} columns; the most that can be brought in is {most}."
            )

    def _passes(
        self, file: dict[str, Any], sheet: str | None, *, count: bool = False
    ) -> Iterator[list[list[str]]]:
        """The rows under the headings, `_PASS_ROWS` at a time, as the Table
        step would give them with every value as written: the file is
        streamed, never held whole. Stops with the limit named when there are
        too many rows. `count` reads one column only (a CSV is then parsed
        lighter)."""
        most = self._ctx.config.import_.max_rows
        seen = 0
        path = self._ctx.file_svc.local_path(file["sha256"])
        name = file["filename"]
        stream: Iterator[list[list[str]]]
        if name.lower().endswith(_EXCEL):
            stream = _excel_rows(
                path, self._ctx.file_svc.retrieve, file["sha256"], sheet, name
            )
        else:
            stream = self._csv_rows(file, path, count)
        for rows in stream:
            seen += len(rows)
            if seen > most:
                raise ValidationError(
                    f"This file has more than {most:,} rows; the most that can "
                    "be brought in is "
                    f"{most:,}."
                )
            yield rows

    def _csv_rows(
        self, file: dict[str, Any], path: Any, count: bool
    ) -> Iterator[list[list[str]]]:
        import pandas as pd

        if path is None:
            path = self._materialise(file["sha256"])
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read(65536)
        delimiter = detect_delimiter(text, [",", "\t", ";"])
        reader = pd.read_csv(
            path,
            sep=delimiter,
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False,
            chunksize=_PASS_ROWS,
            usecols=[0] if count else None,
        )
        try:
            with reader:
                for chunk in reader:
                    yield chunk.values.tolist()
        except UnicodeDecodeError as e:
            raise ValidationError(
                f"Could not decode '{file['filename']}' as utf-8: {e}"
            ) from e
        except pd.errors.EmptyDataError:
            return
        except pd.errors.ParserError as e:
            raise ValidationError(
                f"Could not read '{file['filename']}' as a table: {e}"
            ) from e

    def _materialise(self, sha256: str) -> Path:
        """A file the store keeps off this disk, written to the work folder."""
        assert self._folder is not None
        out = self._folder / "source"
        out.write_bytes(self._ctx.file_svc.retrieve(sha256))
        return out

    def _copy(self, file: dict[str, Any], sheet: str | None) -> dict[str, Any]:
        """The file's rows written once as plain text, with a mark every
        `_BLOCK` rows, so a part is read by going straight to it instead of
        reading the file again from its first row. Made on the first part and
        reused by the rest, whichever process asks."""
        folder = runs_folder().with_name(runs_folder().name + "-import")
        folder.mkdir(parents=True, exist_ok=True)
        tag = hashlib.sha256((sheet or "").encode()).hexdigest()[:12]
        stem = f"{file['sha256']}-{tag}"
        marks = folder / f"{stem}.json"
        body = folder / f"{stem}.csv"
        if marks.exists() and body.exists():
            os.utime(marks)
            return {**json.loads(marks.read_text()), "path": str(body)}
        now = time.time()
        for old in folder.iterdir():
            try:
                if now - old.stat().st_mtime > _COPY_SECONDS:
                    old.unlink()
            except OSError:
                pass
        headings = [str(c) for c in self._read(file, sheet, limit=0).columns]
        self._check_columns(len(headings))
        offsets: list[int] = []
        total = 0
        tmp = folder / f"{stem}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as out:
                for rows in self._passes(file, sheet):
                    for row in rows:
                        if total % _BLOCK == 0:
                            offsets.append(out.tell())
                        buf = io.StringIO()
                        csv.writer(buf, lineterminator="\n").writerow(
                            _fit(row, len(headings))
                        )
                        out.write(buf.getvalue().encode())
                        total += 1
            os.replace(tmp, body)
        finally:
            tmp.unlink(missing_ok=True)
        info = {"headings": headings, "offsets": offsets, "rows": total}
        tmp_marks = folder / f"{stem}.{os.getpid()}.json.tmp"
        tmp_marks.write_text(json.dumps(info))
        os.replace(tmp_marks, marks)
        return {**info, "path": str(body)}

    # -- saving ------------------------------------------------------------

    def run(
        self, spec: ImportSpec, start: int, limit: int, check: bool = False
    ) -> ImportBatch:
        """Bring in rows `start` to `start + limit` of the file (counted under
        the headings). With `check`, nothing is kept: the answer is what the
        save of the same rows would be."""
        if limit < 1 or start < 0:
            raise ValidationError("Say which rows to bring in.")
        limit = min(limit, MAX_BATCH)
        if spec.if_exists not in ("update", "skip", "add_new"):
            raise ValidationError(
                "'If a matching record exists' must be update, skip or add_new."
            )
        ctx = self._ctx
        with self._workspace():
            if check:
                with ctx.validation_scope():
                    return self._run(spec, start, limit)
            with ctx.all_or_nothing():
                return self._run(spec, start, limit)

    def _run(self, spec: ImportSpec, start: int, limit: int) -> ImportBatch:
        ctx = self._ctx
        try:
            dataset = ctx.dataset_svc.get(spec.collection)
            # Said here, as the same refusal as any save, not as a failed step.
            ctx.project.permissions.require(permissions.WRITE_RECORDS, dataset.id)
        except NotFoundError:
            if not spec.new_collection:
                raise
            ctx.dataset_svc.create(spec.collection.strip())
        file = self._file(spec.sha256, spec.filename)
        mapping = self._prepare(spec)
        copy = self._copy(file, spec.sheet)
        df = _batch(copy, start, limit)
        if len(df) == 0:
            return ImportBatch(start, 0, 0, 0, 0, 0, [], True)
        match_on = list(spec.match_on)
        keys = [mapping[h] for h in mapping if mapping[h] in match_on]
        inputs: dict[str, Any] = {"rows": df}
        if start and keys and spec.if_exists != "add_new":
            # Every mapped column, not only the keys: a row that could not
            # be saved (a bad cell) does not hold its key either.
            inputs["earlier"] = _batch(copy, 0, start, only=list(mapping))
        save = _step("civex.save_records@1")
        config = save.config_model(
            schema=spec.kind,
            dataset=spec.collection,
            match_on=match_on,
            if_exists=spec.if_exists,
            field_mapping=mapping,
            as_written=True,
            first_row=start + 2,  # the spreadsheet's own row number
        )
        try:
            out = save.invoke(
                inputs, config, self._workflow_ctx(), STEP_TIMEOUT
            ).outputs
        except PluginExecutionError as e:
            raise ValidationError(_plain(e)) from e
        return ImportBatch(
            start=start,
            read=len(df),
            created=int(out["created"]),
            updated=int(out["updated"]),
            unchanged=int(out["unchanged"]),
            skipped=int(out["skipped"]),
            problems=[str(p) for p in out["skipped_rows"]],
            done=len(df) < limit,
        )

    def _prepare(self, spec: ImportSpec) -> dict[str, str]:
        """Make the kind and the fields the choices call for, if they aren't
        there, and answer the column-to-field mapping the Save step takes.
        Asking again changes nothing."""
        schemas = self._ctx.schema_svc
        try:
            schema = schemas.get(spec.kind)
        except NotFoundError:
            if not spec.kind_label:
                raise
            validate_name(spec.kind, "key")
            schemas.create(spec.kind, label=spec.kind_label)
            schema = schemas.get(spec.kind)
        if schema.parent_id:
            raise ValidationError(
                f"'{schema.name}' records belong inside another record, "
                "so they can't be brought in on their own."
            )
        have = {rf.field.name for rf in schemas.collect_fields(schema)}
        mapping: dict[str, str] = {}
        used: set[str] = set()
        for choice in spec.columns:
            name = choice.field
            if not name:
                continue
            if name in used:
                raise ValidationError(
                    f"Two columns go in '{name}'. Put each column in a field of its own."
                )
            used.add(name)
            if choice.create and name not in have:
                if choice.dtype not in IMPORT_DTYPES:
                    raise ValidationError(
                        f"A column can't be brought in as '{choice.dtype}'."
                    )
                validate_name(name, "key")
                schemas.add_field(
                    spec.kind,
                    name,
                    choice.dtype,
                    label=choice.label or choice.heading,
                )
                have.add(name)
            elif name not in have:
                raise ValidationError(f"There is no field '{name}' to put a column in.")
            mapping[choice.heading] = name
        if not mapping:
            raise ValidationError("Choose at least one column to bring in.")
        for name in spec.match_on:
            if name not in used:
                raise ValidationError(
                    f"'{name}' is used to match rows, so a column must go in it."
                )
        return mapping


_MB = 1024 * 1024


def _mb(size: int) -> str:
    return f"{size / _MB:,.1f} MB"


def _fit(row: list[Any], width: int) -> list[str]:
    row = [("" if v is None else str(v)) for v in row[:width]]
    return row + [""] * (width - len(row))


def _batch(
    copy: dict[str, Any], start: int, limit: int, only: list[str] | None = None
) -> Any:
    """Rows `start` to `start + limit` of the copy as a table of text."""
    import pandas as pd

    headings = copy["headings"]
    offsets = copy["offsets"]
    if start >= copy["rows"] or limit < 1:
        return pd.DataFrame(columns=only or headings, dtype=str)
    block = start // _BLOCK
    lead = start - block * _BLOCK
    with open(copy["path"], "rb") as f:
        f.seek(offsets[block])
        df = pd.read_csv(
            f,
            header=None,
            names=headings,
            dtype=str,
            keep_default_na=False,
            usecols=only,
            nrows=lead + limit,
        )
    return df.iloc[lead:].reset_index(drop=True)


def _excel_rows(
    path: Any, retrieve: Any, sha256: str, sheet: str | None, name: str
) -> Iterator[list[list[str]]]:
    """Rows of one sheet, streamed (openpyxl read-only: the sheet is parsed as
    it is passed, never loaded whole), as the text pandas would give them. Rows
    left empty at the end are dropped, as pandas drops them."""
    import openpyxl

    if name.lower().endswith(".xls"):
        # The old binary format cannot be streamed; its size is already limited.
        import pandas as pd

        try:
            table = pd.read_excel(
                path or io.BytesIO(retrieve(sha256)),
                sheet_name=sheet or 0,
                dtype=str,
                keep_default_na=False,
            )
        except Exception as e:
            raise ValidationError(
                f"'{name}' could not be opened as a spreadsheet: {e}"
            ) from e
        for at in range(0, len(table), _PASS_ROWS):
            yield table.iloc[at : at + _PASS_ROWS].values.tolist()
        return
    source = open(path, "rb") if path is not None else io.BytesIO(retrieve(sha256))
    try:
        book = openpyxl.load_workbook(
            source, read_only=True, data_only=True, keep_links=False
        )
    except Exception as e:
        source.close()
        raise ValidationError(
            f"'{name}' could not be opened as a spreadsheet: {e}"
        ) from e
    try:
        sheet_ = book[sheet] if sheet else book.worksheets[0]
        rows_iter = sheet_.iter_rows(values_only=True)
        next(rows_iter, None)  # the headings
        part: list[list[str]] = []
        blanks: list[list[str]] = []
        for raw in rows_iter:
            row = [_cell(v) for v in raw]
            if not any(row):
                blanks.append(row)
                continue
            if blanks:
                part.extend(blanks)
                blanks = []
            part.append(row)
            if len(part) >= _PASS_ROWS:
                yield part
                part = []
        if part:
            yield part
    finally:
        book.close()
        source.close()


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def _step(plugin_id: str) -> Any:
    step = get_plugin(plugin_id)
    if step is None:
        raise PluginExecutionError(f"The step {plugin_id} is not available.")
    return step


def _plain(e: Exception) -> str:
    """The reason in the words a person reads, without the step's wrapping."""
    text = str(e)
    return text.split(": ", 1)[1] if text.startswith("Step") and ": " in text else text
