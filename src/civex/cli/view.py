from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Optional

import typer

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.services.view_service import rows_to_csv, rows_to_json

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
        export = ctx.view_svc.export(schema_name, view_name)

        if format == "csv":
            body = rows_to_csv(export.view.columns, export.rows).encode("utf-8")
            data_filename = f"{view_name}.csv"
        else:
            body = rows_to_json(export.rows).encode("utf-8")
            data_filename = f"{view_name}.json"

        if not export.file_entries:
            dest = output or Path(data_filename)
            dest.write_bytes(body)
            console.print(f"[success]Wrote {dest}[/success]")
            return

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(data_filename, body)
            for name, ref in export.file_entries:
                try:
                    data = ctx.file_svc.retrieve(ref.sha256)
                except Exception:
                    console.print(
                        f"[error]Object {ref.sha256} not found locally or "
                        "on remote[/error]"
                    )
                    raise typer.Exit(1)
                zf.writestr(name, data)

        dest = output or Path(f"{view_name}.zip")
        dest.write_bytes(buf.getvalue())
        console.print(f"[success]Wrote {dest}[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
