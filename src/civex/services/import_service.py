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

import logging
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from civex_plugin_sdk.io_convert import to_invoke_form

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
from civex.plugins.runtime import new_run_dir

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
        return {"sha256": sha256, "filename": filename, "size": size}

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
            # Count the rest from one column only, so a long file costs little.
            total = len(self._read(file, sheet, only=[headings[0]]))
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
            with pd.ExcelFile(io.BytesIO(self._ctx.file_svc.retrieve(sha256))) as book:
                return [str(n) for n in book.sheet_names]
        except Exception as e:  # a file that is no Excel file, however it fails
            raise ValidationError(
                f"'{filename}' could not be opened as a spreadsheet: {e}"
            ) from e

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
            ctx.dataset_svc.get(spec.collection)
        except NotFoundError:
            if not spec.new_collection:
                raise
            ctx.dataset_svc.create(spec.collection.strip())
        file = self._file(spec.sha256, spec.filename)
        mapping = self._prepare(spec)
        df = self._read(file, spec.sheet, skip=start, limit=limit)
        if len(df) == 0:
            return ImportBatch(start, 0, 0, 0, 0, 0, [], True)
        match_on = list(spec.match_on)
        keys = [mapping[h] for h in mapping if mapping[h] in match_on]
        inputs: dict[str, Any] = {"rows": df}
        if start and keys and spec.if_exists != "add_new":
            by_field = {v: k for k, v in mapping.items()}
            earlier = self._read(
                file,
                spec.sheet,
                limit=start,
                only=[by_field[k] for k in keys],
            )
            inputs["earlier"] = earlier
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


def _step(plugin_id: str) -> Any:
    step = get_plugin(plugin_id)
    if step is None:
        raise PluginExecutionError(f"The step {plugin_id} is not available.")
    return step


def _plain(e: Exception) -> str:
    """The reason in the words a person reads, without the step's wrapping."""
    text = str(e)
    return text.split(": ", 1)[1] if text.startswith("Step") and ": " in text else text
