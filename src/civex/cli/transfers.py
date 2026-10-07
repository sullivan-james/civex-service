"""`civex store move` and `civex store transfers`: moving files between volumes."""

from __future__ import annotations

from typing import Optional

import typer

from civex.cli.utils import format_bytes, get_ctx
from civex.console import console
from civex.domain.exceptions import CivexError
from civex.domain.transfers import (
    KIND_CONSOLIDATE,
    KIND_DRAIN,
    RESUMABLE,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TransferProgress,
    TransferRecord,
    TransferSpec,
)
from civex.services.transfer_engine import TransferControl

transfers_app = typer.Typer(
    help="Look at, pause, resume and cancel moves of files between volumes",
    no_args_is_help=True,
)


def _eta(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else f"{m}m {s}s"


def _summary(record: TransferRecord) -> None:
    p = record.progress
    console.print(
        f"[bold]{record.id[:8]}[/bold] {record.kind}  [cyan]{record.status}[/cyan]  "
        f"{p.files_done}/{p.files_total} files, "
        f"{format_bytes(p.bytes_done)} of {format_bytes(p.bytes_total)}"
    )
    if record.pause_reason:
        console.print(f"  [yellow]{record.pause_reason}[/yellow]")
    if record.error:
        console.print(f"  [red]{record.error}[/red]")
    if p.files_failed:
        console.print(f"  [red]{p.files_failed} file(s) could not be moved.[/red]")


def _print_plan(spec: TransferSpec, ctx) -> bool:
    plan = ctx.transfer_svc.plan(spec)
    console.print(
        f"Would move [bold]{plan.files}[/bold] files ({format_bytes(plan.bytes)}); "
        f"{plan.already_there} already on a target."
    )
    for t in plan.targets:
        console.print(
            f"  → {t.volume}: about {t.files} files ({format_bytes(t.bytes)}), "
            f"{format_bytes(t.free_bytes)} free"
        )
    for w in plan.warnings:
        console.print(f"  [yellow]! {w}[/yellow]")
    for prob in plan.problems:
        console.print(f"  [red]✗ {prob}[/red]")
    return plan.can_proceed


def _run_queue(highlight: str | None = None) -> None:
    """Run the queue in this terminal, with a live progress bar: every waiting
    transfer, oldest first, each as its own bar. Ctrl+C pauses the running one
    (nothing is lost). If another process is already moving files (the server,
    or another terminal) it is left to finish the queue, and this says so."""
    from rich.progress import (
        BarColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
    )

    from civex.services.transfer_worker import TransferWorker

    current: dict[str, object] = {}
    worker = TransferWorker(get_ctx)
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    ) as bar:
        task = bar.add_task("Moving", total=1)

        def began(transfer_id: str, control: TransferControl) -> None:
            current.update(id=transfer_id, control=control)
            bar.reset(task, total=1, description=f"Moving {transfer_id[:8]}")

        def show(transfer_id: str, p: TransferProgress) -> None:
            total = max(p.bytes_total, 1)
            bar.update(
                task,
                total=total,
                completed=min(p.bytes_done + p.current_bytes, total),
                description=(
                    f"Moving {transfer_id[:8]}  {p.files_done}/{p.files_total} files"
                    + (
                        f"  {format_bytes(p.rate_bytes_per_second)}/s"
                        if p.rate_bytes_per_second
                        else ""
                    )
                ),
            )

        try:
            result = worker.drain(on_job_start=began, on_progress=show)
        except KeyboardInterrupt:
            control = current.get("control")
            transfer_id = current.get("id")
            console.print("\n[yellow]Pausing…[/yellow]")
            if isinstance(control, TransferControl) and isinstance(transfer_id, str):
                control.pause()
                ctx = get_ctx()
                try:
                    paused = ctx.transfer_svc.execute(
                        transfer_id, control, lambda p: show(transfer_id, p)
                    )
                finally:
                    ctx.close()
                _summary(paused)
            return
    for record in result.ran:
        _summary(record)
    if result.busy:
        console.print(
            "[yellow]Another move is already running (the server, or another "
            "terminal). Yours is queued and starts when it finishes; "
            "`civex store transfers list` shows where things stand.[/yellow]"
        )
    elif highlight is not None and not any(r.id == highlight for r in result.ran):
        console.print(
            f"[yellow]{highlight[:8]} did not run. See "
            f"`civex store transfers show {highlight[:8]}`.[/yellow]"
        )


def _start(spec: TransferSpec, dry_run: bool) -> None:
    ctx = get_ctx()
    try:
        ok = _print_plan(spec, ctx)
        if dry_run:
            return
        if not ok:
            raise typer.Exit(1)
        record = ctx.transfer_svc.create(spec)
        console.print(
            f"Queued {record.id[:8]}. Ctrl+C pauses; resume with "
            f"`civex store transfers resume {record.id[:8]}`."
        )
    except CivexError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    _run_queue(record.id)


def move(
    to: list[str] = typer.Option(
        ..., "--to", help="Volume to put files on (repeat for several, in order)."
    ),
    off: Optional[list[str]] = typer.Option(
        None, "--off", help="Empty this volume (repeatable)."
    ),
    collection: Optional[list[str]] = typer.Option(
        None,
        "--collection",
        help="Gather this collection's files onto the target (repeatable).",
    ),
    verify_full: bool = typer.Option(
        False, "--verify-full", help="Read every copy back and check it (slower)."
    ),
    keep_writable: bool = typer.Option(
        False, "--keep-writable", help="Don't make the source read-only while draining."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would move and stop."
    ),
) -> None:
    """Move stored files between volumes.

    Use --off to empty a volume, or --collection to gather a collection's
    files onto one volume. Each file is copied and checked before the original
    is removed, so stopping at any moment, even a power cut, loses nothing.
    Moves run one at a time: if one is already running, this one is queued
    behind it. Ctrl+C pauses; resume later with `civex store transfers resume`.
    """
    if bool(off) == bool(collection):
        console.print("[red]Give either --off or --collection.[/red]")
        raise typer.Exit(2)
    ids: list[str] = []
    if collection:
        ctx = get_ctx()
        try:
            ids = [str(ctx.dataset_svc.get(n).id) for n in collection]
        except CivexError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        finally:
            ctx.close()
    spec = TransferSpec(
        kind=KIND_DRAIN if off else KIND_CONSOLIDATE,
        targets=list(to),
        sources=list(off or []),
        collection_ids=ids,
        verify="full" if verify_full else "copy",
        freeze_sources=not keep_writable,
    )
    _start(spec, dry_run)


def _find(ctx, prefix: str) -> TransferRecord:
    matches = [r for r in ctx.transfer_svc.recent(200) if r.id.startswith(prefix)]
    if len(matches) != 1:
        console.print(
            f"[red]{'No' if not matches else 'More than one'} transfer matches '{prefix}'.[/red]"
        )
        raise typer.Exit(1)
    return matches[0]


@transfers_app.command("list")
def transfers_list() -> None:
    """List recent transfers, newest first."""
    ctx = get_ctx()
    try:
        records = ctx.transfer_svc.recent()
        if not records:
            console.print("[dim]No transfers yet.[/dim]")
        for r in records:
            _summary(r)
    finally:
        ctx.close()


@transfers_app.command("show")
def transfers_show(
    transfer: str = typer.Argument(
        ..., help="Transfer id (the first few characters are enough)."
    ),
) -> None:
    """Show a transfer's progress, speed and any files that could not be moved."""
    ctx = get_ctx()
    try:
        record = ctx.transfer_svc.get(_find(ctx, transfer).id)
        _summary(record)
        p = record.progress
        if record.status == STATUS_RUNNING:
            console.print(
                f"  {format_bytes(p.rate_bytes_per_second)}/s, about {_eta(p.eta_seconds)} left"
            )
        for f in record.failures:
            console.print(f"  [red]{f.sha256[:12]} on {f.volume}: {f.reason}[/red]")
    finally:
        ctx.close()


@transfers_app.command("pause")
def transfers_pause(transfer: str = typer.Argument(..., help="Transfer id.")) -> None:
    """Ask a transfer to pause (it keeps what it has moved); a waiting one is
    taken out of the queue."""
    ctx = get_ctx()
    try:
        ctx.transfer_svc.request_control(_find(ctx, transfer).id, "pause")
        console.print("Pause requested.")
    except CivexError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@transfers_app.command("cancel")
def transfers_cancel(transfer: str = typer.Argument(..., help="Transfer id.")) -> None:
    """Stop a transfer for good. Nothing already moved is moved back."""
    ctx = get_ctx()
    try:
        record = _find(ctx, transfer)
        if record.status == STATUS_RUNNING:
            ctx.transfer_svc.request_control(record.id, "cancel")
            console.print("Cancel requested.")
        elif record.status == STATUS_QUEUED:
            _summary(ctx.transfer_svc.request_control(record.id, "cancel"))
        else:
            _summary(ctx.transfer_svc.cancel_idle(record.id))
    except CivexError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@transfers_app.command("resume")
def transfers_resume(transfer: str = typer.Argument(..., help="Transfer id.")) -> None:
    """Queue a paused, failed or interrupted transfer again and run the queue in
    this terminal."""
    ctx = get_ctx()
    try:
        record = _find(ctx, transfer)
        if record.status not in RESUMABLE:
            console.print(f"[red]It is {record.status}; nothing to resume.[/red]")
            raise typer.Exit(1)
        ctx.transfer_svc.begin_resume(record.id)
    except CivexError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    _run_queue(record.id)


@transfers_app.command("run")
def transfers_run() -> None:
    """Run the waiting moves in this terminal, oldest first.

    Moves normally start by themselves as soon as they are queued, by this
    terminal or the server. Use this to carry on a queue left waiting (the
    server isn't running, say). Ctrl+C pauses the running move.
    """
    _run_queue()
