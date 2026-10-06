from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

import typer

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.naming import safe_filename
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.tables import FORMATS
from civex.services.archive import build_download

app = typer.Typer(help="Export saved views")


@app.command("export")
def view_export(
    schema_name: str = typer.Argument(..., help="Schema the view belongs to"),
    view_name: str = typer.Argument(..., help="View name"),
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help=f"Output format: one of {', '.join(FORMATS)}",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination file. Defaults to '<view>.<format>', or '<view>.zip' "
        "when the view includes file/file_list columns.",
    ),
) -> None:
    """Export a saved view's rows, honoring its saved filter/sort and
    flattening joined columns (text formats use the dotted "ref_field.target_field"
    header; json nests them). Any file/file_list column is bundled into a zip
    alongside the table. `civex files export --view` makes the same thing as a
    folder.
    """
    if format not in FORMATS:
        console.print(f"[error]--format must be one of: {', '.join(FORMATS)}[/error]")
        raise typer.Exit(1)

    ctx = _ctx()
    scratch = Path(tempfile.mkdtemp(prefix="civex-view-"))
    try:
        svc = ctx.file_access_svc
        selection = ctx.view_svc.table_selection(schema_name, view_name, format)
        plan = svc.plan(selection)
        name = safe_filename(view_name)
        download = build_download(svc, ctx.file_svc, selection, plan, scratch, name)
        dest = output or Path(download.filename)
        shutil.move(str(download.path), dest)
        console.print(f"[success]Wrote {dest}[/success]")
        if svc.missing_note(plan):
            console.print(
                "[warning]Some files could not be reached and are left out; "
                "MISSING.txt in the zip lists them.[/warning]"
            )
    except FileNotFoundError:
        console.print(
            "[error]A file in this export was not found locally or on remote[/error]"
        )
        raise typer.Exit(1)
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        ctx.close()
