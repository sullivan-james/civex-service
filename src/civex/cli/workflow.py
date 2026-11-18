from __future__ import annotations

import glob as _glob
import logging
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from civex.cli.utils import cli_load_config, drain_jobs, get_ctx
from civex.console import console
from civex.domain.exceptions import CivexError, NotFoundError, WorkflowValidationError
from civex.workflows.definition import WorkflowDef, load_workflow

log = logging.getLogger(__name__)

app = typer.Typer(help="Manage and run data processing workflows")

_INPUT_STEP = "__input__"


def _find_workflow(name: str, workflows_dir: Path) -> WorkflowDef | None:
    if not workflows_dir.exists():
        return None
    for path in sorted(workflows_dir.glob("*.yaml")) + sorted(
        workflows_dir.glob("*.yml")
    ):
        try:
            candidate = load_workflow(path)
            if candidate.name == name or path.stem == name:
                return candidate
        except Exception as e:
            log.warning("Skipping unparseable workflow file %s: %s", path, e)
            continue
    return None


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
    config = cli_load_config()
    workflows_dir = config.civex_dir / "workflows"
    if not workflows_dir.exists():
        console.print("[info]No workflows directory. Run `civex init` first.[/info]")
        return

    yamls = sorted(workflows_dir.glob("*.yaml")) + sorted(workflows_dir.glob("*.yml"))
    if not yamls:
        console.print(
            "[info]No workflows defined. Add a YAML file to _civex/workflows/.[/info]"
        )
        return

    table = Table("Name", "On", "Description", "Steps", "Inputs", "File")
    for path in yamls:
        try:
            wf = load_workflow(path)
            inputs_summary = (
                ", ".join(f"{k} ({v.type})" for k, v in (wf.inputs or {}).items())
                or "—"
            )
            table.add_row(
                wf.name,
                "yes" if wf.enabled else "[dim]off[/dim]",
                wf.description or "",
                str(len(wf.steps)),
                inputs_summary,
                path.name,
            )
        except Exception as e:
            table.add_row(path.stem, "-", f"[error]{e}[/error]", "-", "-", path.name)
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
    config = cli_load_config()
    wf_def = _find_workflow(name, config.civex_dir / "workflows")
    if wf_def is None:
        console.print(
            f"[error]Workflow '{name}' not found in {config.civex_dir / 'workflows'}[/error]"
        )
        raise typer.Exit(1)

    app_ctx = get_ctx()

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


def _show_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, dict) and "filename" in value:
        return str(value["filename"])
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return ", ".join(str(v.get("filename", v)) for v in value)
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "…"


@app.command("try")
def workflow_try(
    name: str = typer.Argument(
        ..., help="Workflow name, filename stem, or a path to a YAML file"
    ),
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
    """Try a workflow on a record without keeping anything it does.

    It runs as a real run would, then everything it wrote is undone, and what
    it would have done is printed: the records it would create, change or
    delete, with each value before and after, and the runs its saves would
    start. Works whether the workflow is on or off. A plugin that reaches
    outside civex (a web request, a file of its own) still does so.
    """
    from civex.workflows.trial import try_workflow

    config = cli_load_config()
    app_ctx = get_ctx()
    try:
        as_path = Path(name)
        if as_path.suffix in (".yaml", ".yml") and as_path.exists():
            wf_def = app_ctx.workflow_svc.check(as_path.read_text(encoding="utf-8"))
        else:
            found = _find_workflow(name, config.civex_dir / "workflows")
            if found is None:
                console.print(f"[error]Workflow '{name}' not found[/error]")
                raise typer.Exit(1)
            wf_def = found
        input_data = _resolve_inputs(wf_def, input_args, app_ctx) or None
        result = try_workflow(app_ctx, wf_def, record_id, input_data)
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        app_ctx.rollback()
        app_ctx.close()

    for step in result.steps:
        mark = {"success": "✓", "skipped": "⏭", "failed": "✗"}.get(step["status"], "?")
        console.print(f"  {mark} {step['step_id']} [dim]({step['plugin']})[/dim]")
    if result.error:
        console.print(
            f"[error]Step '{result.error.get('step')}' failed: "
            f"{result.error.get('message')}[/error]"
        )
    if not result.changes:
        console.print("[info]It would change no records.[/info]")
    for change in result.changes:
        title = change.name or change.record_id[:8]
        console.print(
            f"\n[bold]{change.action.capitalize()}[/bold] {change.schema_name} {title}"
        )
        if change.fields:
            table = Table("Field", "Before", "After")
            for f in change.fields:
                table.add_row(f.label, _show_value(f.before), _show_value(f.after))
            console.print(table)
    for workflow, count in result.would_start.items():
        console.print(f"[info]Would start '{workflow}' on {count} record(s).[/info]")
    console.print("[dim]Nothing was kept.[/dim]")
    if result.error:
        raise typer.Exit(1)


def _switch(stem: str, enabled: bool) -> None:
    app_ctx = get_ctx()
    try:
        app_ctx.workflow_svc.set_enabled(stem, enabled)
    except WorkflowValidationError as e:
        for err in e.errors:
            console.print(
                f"[error]{err['step'] or 'workflow'}: {err['message']}[/error]"
            )
        raise typer.Exit(1)
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        app_ctx.close()
    state = (
        "on: its triggers start runs"
        if enabled
        else ("off: it runs only when started by hand")
    )
    console.print(f"[success]'{stem}' is {state}.[/success]")


@app.command("enable")
def workflow_enable(
    stem: str = typer.Argument(..., help="Workflow filename stem"),
) -> None:
    """Switch a workflow on, so its triggers start runs."""
    _switch(stem, True)


@app.command("disable")
def workflow_disable(
    stem: str = typer.Argument(..., help="Workflow filename stem"),
) -> None:
    """Switch a workflow off: its triggers start nothing, and it runs only when
    someone starts or tries it."""
    _switch(stem, False)
