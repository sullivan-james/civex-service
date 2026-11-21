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

app = typer.Typer(help="Saved views and saved analyses: show, save, export")


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


@app.command("show")
def view_show(
    schema_name: str = typer.Argument(..., help="Schema the view belongs to"),
    view_name: str = typer.Argument(..., help="View name"),
) -> None:
    """Show a saved view: its filter, columns and sort, and for a saved
    analysis what it groups by and works out, with the summary worked out over
    the records it lists now."""
    import json

    from civex.cli.record import print_summary

    ctx = _ctx()
    try:
        view = ctx.view_svc.get(schema_name, view_name)
        console.print(f"[bold]{view.name}[/bold] ({view.schema_name})")
        console.print(
            "Filter: " + (json.dumps(view.filter_tree) if view.filter_tree else "none")
        )
        if view.columns:
            console.print("Columns: " + ", ".join(view.columns))
        if view.sort:
            console.print(
                "Sort: "
                + ", ".join(
                    f"{s['field']} {s.get('direction', 'asc')}" for s in view.sort
                )
            )
        if view.summary is None:
            console.print("A saved filter (no summary).")
            return
        s = view.summary
        console.print("A saved analysis.")
        console.print("Group by: " + (", ".join(s["group_by"]) or "nothing (a total)"))
        console.print("Work out: " + ", ".join(s["measures"]))
        console.print(f"Shown as: {s['show']}")
        print_summary(ctx.view_svc.summarise(schema_name, view_name))
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("save-analysis")
def view_save_analysis(
    schema_name: str = typer.Argument(..., help="The kind of record summarised"),
    view_name: str = typer.Argument(
        ..., help="The analysis's name: a saved view of that kind"
    ),
    by: Optional[list[str]] = typer.Option(
        None,
        "--summary-by",
        "--by",
        "-b",
        help="Group by a field (repeatable, up to 3), as 'civex record summarise "
        "--by' takes it.",
    ),
    measure: Optional[list[str]] = typer.Option(
        None,
        "--summary-measure",
        "--measure",
        "-m",
        help="What to work out (repeatable), as 'civex record summarise "
        "--measure' takes it; 'count' when none is given.",
    ),
    collection: Optional[str] = typer.Option(
        None, "--in", help="The collection it is about (omit for every collection)"
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-q", help="Only records whose values contain this text"
    ),
    chart: bool = typer.Option(
        False, "--chart", help="Show it as a chart rather than a table"
    ),
) -> None:
    """Save a summary as an analysis: a saved view that opens the explorer's
    Summary and can be put on the Analytics page. An existing view of that
    name keeps its filter and becomes (or stays) an analysis with these
    choices; otherwise a new view is made with no filter."""
    ctx = _ctx()
    try:
        collection_id = None
        if collection:
            collection_id = str(ctx.dataset_svc.get(collection).id)
        summary = {
            "group_by": list(by or []),
            "measures": list(measure or ["count"]),
            "show": "chart" if chart else "table",
            "collection": collection_id,
            "search": search,
        }
        try:
            ctx.view_svc.get(schema_name, view_name)
            ctx.view_svc.update(schema_name, view_name, summary=summary)
            done = "Updated"
        except NotFoundError:
            ctx.view_svc.create(schema_name, view_name, summary=summary)
            done = "Saved"
        ctx.commit()
        console.print(f"[success]{done} the analysis '{view_name}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
