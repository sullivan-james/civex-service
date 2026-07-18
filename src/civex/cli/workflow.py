from __future__ import annotations

import glob as _glob
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from civex.cli.utils import drain_jobs, get_ctx
from civex.console import console
from civex.domain.exceptions import NotFoundError
from civex.workflows.definition import WorkflowDef

app = typer.Typer(help="Manage and run data processing workflows")

_INPUT_STEP = "__input__"


def _resolve_inputs(
    wf_def: WorkflowDef,
    raw_args: list[str],
    app_ctx: Any,
) -> dict[str, dict[str, Any]]:
    """Parse --input name=value args and resolve them against the workflow's declared inputs.

    Returns initial_outputs seeded under the "__input__" virtual step key, or an empty
    dict if no inputs were provided.
    """
    if not raw_args:
        return {}

    declared = wf_def.inputs or {}
    resolved: dict[str, Any] = {}

    for arg in raw_args:
        if "=" not in arg:
            console.print(
                f"[error]--input must be in name=value format, got: {arg}[/error]"
            )
            raise typer.Exit(1)
        input_name, value = arg.split("=", 1)

        decl = declared.get(input_name)
        if decl is None:
            console.print(
                f"[error]Workflow has no declared input '{input_name}'. "
                f"Declared inputs: {list(declared.keys()) or 'none'}[/error]"
            )
            raise typer.Exit(1)

        if decl.type == "files":
            paths = sorted(_glob.glob(value, recursive=True))
            if not paths:
                console.print(f"[error]No files matched: {value}[/error]")
                raise typer.Exit(1)
            refs = []
            for p in paths:
                file_path = Path(p)
                ref = app_ctx.file_svc.store(file_path)
                refs.append(ref.to_dict())
                console.print(f"  stored {file_path.name} ({ref.size} bytes)")
            resolved[input_name] = refs

        elif decl.type == "value":
            resolved[input_name] = value

        else:
            console.print(
                f"[error]Unknown input type '{decl.type}' for input '{input_name}'[/error]"
            )
            raise typer.Exit(1)

    return {_INPUT_STEP: resolved}


@app.command("list")
def workflow_list() -> None:
    """List all workflow definitions in _civex/workflows/."""
    ctx = get_ctx()
    defs = ctx.workflow_svc.list_defs()
    if not defs:
        console.print(
            "[info]No workflows defined. Add a YAML file to _civex/workflows/.[/info]"
        )
        return

    table = Table("Name", "Description", "Steps", "Inputs", "File")
    for path, wf in defs:
        inputs_summary = (
            ", ".join(f"{k} ({v.type})" for k, v in (wf.inputs or {}).items()) or "—"
        )
        table.add_row(
            wf.name,
            wf.description or "",
            str(len(wf.steps)),
            inputs_summary,
            path.name,
        )
    console.print(table)


@app.command("run")
def workflow_run(
    name: str = typer.Argument(..., help="Workflow name or filename stem"),
    record_id: str = typer.Option(
        ..., "--record", "-r", help="Record ID or short prefix"
    ),
    input_args: list[str] = typer.Option(
        [],
        "--input",
        "-i",
        help="Workflow input as name=value. For 'files' inputs, value is a glob pattern.",
    ),
) -> None:
    """Run a workflow against a specific record.

    Declared workflow inputs can be supplied with --input name=value.
    For inputs of type 'files', value is a glob pattern (e.g. --input files=*.csv).
    Supplied values are pre-seeded as __input__.<name> and can be referenced in
    step inputs like: files: __input__.files
    """
    app_ctx = get_ctx()
    wf_def = app_ctx.workflow_svc.find_by_name(name)
    if wf_def is None:
        console.print(
            f"[error]Workflow '{name}' not found in {app_ctx.workflow_svc.workflows_dir}[/error]"
        )
        raise typer.Exit(1)

    try:
        record = app_ctx.record_svc.get(record_id)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    if wf_def.record_schema and record.schema_name != wf_def.record_schema:
        console.print(
            f"[error]Workflow '{wf_def.name}' requires a {wf_def.record_schema} record, "
            f"got {record.schema_name}[/error]"
        )
        raise typer.Exit(1)

    initial_outputs = _resolve_inputs(wf_def, input_args, app_ctx)

    job = app_ctx.job_svc.enqueue_manual(
        wf_def.name, record, input_data=initial_outputs or None
    )
    app_ctx.commit()
    console.print(f"Enqueued job {str(job.id)[:8]}… — draining queue")

    drain_jobs(app_ctx)
