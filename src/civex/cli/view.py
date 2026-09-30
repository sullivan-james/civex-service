from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

import typer

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.services.archive import write_zip
from civex.services.view_service import write_csv, write_json

app = typer.Typer(help="Export saved views")


@app.command("export")
def view_export(
    schema_name: str = typer.Argument(..., help="Schema the view belongs to"),
    view_name: str = typer.Argument(..., help="View name"),
    format: str = typer.Option(
        "csv", "--format", "-f", help="Output format: 'csv' or 'json'"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination file. Defaults to '<view>.csv'/'.json', or "
        "'<view>.zip' when the view includes file/file_list columns.",
    ),
) -> None:
    """Export a saved view's rows, honoring its saved filter/sort and
    flattening joined columns (CSV headers use the dotted
    "ref_field.target_field" convention; JSON nests them instead). Any
    file/file_list column is bundled into a zip alongside the CSV/JSON.
    """
    if format not in ("csv", "json"):
        console.print("[error]--format must be 'csv' or 'json'[/error]")
        raise typer.Exit(1)

    ctx = _ctx()
    try:
        stream = ctx.view_svc.export_stream(schema_name, view_name)
        file_entries: list = []

        def row_batches():
            for batch in stream.batches:
                file_entries.extend(batch.file_entries)
                yield batch.rows

        data_filename = f"{view_name}.{format}"
        # Write the data file straight to its final destination when there
        # are no files to bundle; otherwise to a scratch file that gets
        # zipped. Either way rows are paged, never all held in memory.
        data_path = Path(tempfile.mkstemp(prefix="civex-view-", suffix=f".{format}")[1])
        try:
            with data_path.open("w", encoding="utf-8", newline="") as out:
                if format == "csv":
                    write_csv(out, stream.view.columns, row_batches())
                else:
                    write_json(out, row_batches())

            if not file_entries:
                dest = output or Path(data_filename)
                shutil.move(str(data_path), dest)
                console.print(f"[success]Wrote {dest}[/success]")
                return

            dest = output or Path(f"{view_name}.zip")
            try:
                write_zip(
                    dest,
                    ctx.file_svc,
                    file_entries,
                    data_member=(data_filename, data_path),
                )
            except Exception:
                dest.unlink(missing_ok=True)
                console.print(
                    "[error]A file in this export was not found locally or "
                    "on remote[/error]"
                )
                raise typer.Exit(1)
            console.print(f"[success]Wrote {dest}[/success]")
        finally:
            data_path.unlink(missing_ok=True)
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
