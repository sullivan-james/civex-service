from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import drain_jobs, get_ctx as _ctx
from civex.console import console
from civex.domain.dtos import FileRef
from civex.domain.field_descriptors import COMPUTED_DTYPES
from civex.domain.exceptions import (
    CoercionError,
    NotAllowedError,
    NotFoundError,
    ValidationError,
)

app = typer.Typer(help="Manage records")


@app.command("add")
def record_add(
    dataset_name: str = typer.Option(..., "--to", help="Dataset to add the record to"),
    schema_name: str = typer.Option(
        ..., "--schema", "-s", help="Schema for this record"
    ),
) -> None:
    """Add a record, prompting for each field defined on the schema."""
    ctx = _ctx()
    try:
        dataset = ctx.dataset_svc.get(dataset_name)
        schema = ctx.schema_svc.get(schema_name)
        fields = ctx.record_svc.get_resolved_fields(schema_name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    # Prompt for parent record ID if this is a child schema.
    parent_record_id: str | None = None
    if schema.parent_id:
        parent_schema = ctx.schema_svc.get_by_id(schema.parent_id)
        parent_schema_name = parent_schema.name if parent_schema else "unknown"
        while True:
            raw_id = typer.prompt(f"  Parent record ID ({parent_schema_name})")
            try:
                parent_record = ctx.record_svc.get(raw_id)
                if parent_record.dataset_id != dataset.id:
                    console.print(
                        f"[error]  Parent record must be in dataset '{dataset_name}'.[/error]"
                    )
                    continue
                console.print(f"  [dim]↑ {parent_schema_name} record[/dim]")
                parent_record_id = raw_id
                break
            except NotFoundError:
                console.print(
                    f"[error]  Record '{raw_id}' not found — try again.[/error]"
                )

    if not fields:
        console.print("[warning]Schema has no own fields.[/warning]")

    collection_timezone = dataset.timezone
    data: dict = {}
    for rf in fields:
        if rf.field.dtype in COMPUTED_DTYPES:
            continue  # a formula is worked out, never typed in
        dtype_label = rf.field.dtype
        if rf.field.dtype == "reference" and rf.field.restrictions.get("schema"):
            dtype_label = f"reference → {rf.field.restrictions['schema']}"
        label = f"  {rf.field.name} ({dtype_label})"
        if rf.field.required:
            label += " [required]"

        while True:
            raw = typer.prompt(label, default="" if not rf.field.required else ...)
            if raw == "" and not rf.field.required:
                break
            try:
                data[rf.field.name] = ctx.record_svc.coerce_value(
                    raw,
                    rf.field.dtype,
                    rf.field.name,
                    rf.field.restrictions,
                    timezone=collection_timezone,
                    collection_id=str(dataset.id),
                )
                break
            except CoercionError as e:
                console.print(f"[error]  {e}[/error]")

    try:
        record = ctx.record_svc.add(
            dataset_name, schema_name, data, parent_record_id=parent_record_id
        )
        ctx.commit()
        console.print(f"[success]Added record {record.id}.[/success]")
        drain_jobs(ctx)
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("show")
def record_show(
    record_id: str = typer.Argument(..., help="Record ID or short prefix"),
) -> None:
    """Show a record's field values."""
    ctx = _ctx()
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    console.print(f"[bold]Record {record.id}[/bold]")
    console.print(f"  Schema    {record.schema_name}")
    console.print(f"  Dataset   {record.dataset_id}")
    if record.parent_record_id:
        console.print(f"  Parent    {record.parent_record_id}")
    console.print(f"  Created   {record.created_at.strftime('%Y-%m-%d %H:%M UTC')}")

    if record.data:
        table = Table("Field", "Value")
        for k, v in record.data.items():
            if isinstance(v, dict) and "sha256" in v:
                ref = FileRef.from_dict(v)
                display = (
                    f"{ref.filename} ({ref.size} bytes, sha256:{ref.sha256[:12]}…)"
                )
            else:
                display = str(v)
            table.add_row(k, display)
        for k, v in (record.derived or {}).items():
            problem = (record.formula_errors or {}).get(k)
            table.add_row(
                k,
                f"[dim](can't be worked out: {problem})[/dim]" if problem else str(v),
            )
        console.print(table)
    else:
        console.print("  (no field values)")


@app.command("update")
def record_update(
    record_id: str = typer.Argument(..., help="Record ID or short prefix"),
) -> None:
    """Update a record's field values, prompting for each field."""
    ctx = _ctx()
    try:
        record = ctx.record_svc.get(record_id)
        fields = ctx.record_svc.get_resolved_fields(record.schema_name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    collection_timezone = (
        ctx.dataset_svc.get_by_id(record.dataset_id).timezone
        if record.dataset_id
        else None
    )
    data = dict(record.data)
    for rf in fields:
        if rf.field.dtype in COMPUTED_DTYPES:
            continue  # a formula is worked out, never typed in
        current = data.get(rf.field.name, "")
        dtype_label = rf.field.dtype
        if rf.field.dtype == "reference" and rf.field.restrictions.get("schema"):
            dtype_label = f"reference → {rf.field.restrictions['schema']}"
        label = f"  {rf.field.name} ({dtype_label})"
        if rf.field.required:
            label += " [required]"

        while True:
            raw = typer.prompt(f"{label} [current: {current}]", default=str(current))
            if raw == "" and not rf.field.required:
                data.pop(rf.field.name, None)
                break
            try:
                data[rf.field.name] = ctx.record_svc.coerce_value(
                    raw,
                    rf.field.dtype,
                    rf.field.name,
                    rf.field.restrictions,
                    timezone=collection_timezone,
                    collection_id=str(record.dataset_id),
                )
                break
            except CoercionError as e:
                console.print(f"[error]  {e}[/error]")

    ctx.record_svc.update(record_id, data)
    ctx.commit()
    console.print(f"[success]Updated record {record.id}.[/success]")
    drain_jobs(ctx)


@app.command("find")
def record_find(
    dataset_name: str = typer.Option(..., "--in", help="Dataset to search"),
    schema_name: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Filter by schema"
    ),
    where: Optional[list[str]] = typer.Option(
        None, "--where", help="field=value filter (repeatable)"
    ),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        "-q",
        help="Text to look for in the records' values (text, numbers, list "
        "items, file names), ignoring case. A record id prefix matches too.",
    ),
    search_field: Optional[list[str]] = typer.Option(
        None,
        "--search-field",
        help="Look for the --search text only in this field (repeatable). "
        "Needs --schema.",
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum records to return"),
) -> None:
    """List records in a dataset. Use --schema to filter by type and show field
    columns, and --search to find records by what they hold."""
    ctx = _ctx()
    try:
        records = ctx.record_svc.find(
            dataset_name,
            schema_name=schema_name,
            filters=where or [],
            search=search,
            search_fields=search_field or None,
            limit=limit,
        )
    except (NotFoundError, ValidationError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    if not records:
        console.print("[info]No records match.[/info]")
        return

    if schema_name:
        fields = ctx.record_svc.get_resolved_fields(schema_name)
        field_names = [rf.field.name for rf in fields]
        table = Table("ID", *field_names, "Created")
        for r in records:
            row_vals = []
            for f in field_names:
                v = r.data.get(f, (r.derived or {}).get(f, ""))
                if isinstance(v, dict) and "sha256" in v:
                    row_vals.append(FileRef.from_dict(v).filename)
                else:
                    row_vals.append(str(v))
            table.add_row(
                str(r.id)[:8] + "…", *row_vals, r.created_at.strftime("%Y-%m-%d")
            )
    else:
        table = Table("ID", "Schema", "Created")
        for r in records:
            table.add_row(
                str(r.id)[:8] + "…", r.schema_name, r.created_at.strftime("%Y-%m-%d")
            )

    console.print(table)


@app.command("summarise")
def record_summarise(
    collection: Optional[str] = typer.Option(
        None, "--in", help="The collection (omit for every collection)"
    ),
    schema: str = typer.Option(
        ..., "--schema", "-s", help="The kind of record to summarise"
    ),
    by: Optional[list[str]] = typer.Option(
        None,
        "--by",
        "-b",
        help="Group by a field (repeatable, up to 3): 'field', or 'kind.field' "
        "for a field of a kind above; add ':year', ':month', ':week' or ':day' "
        "for a date, or ':5' for a number in ranges 5 wide.",
    ),
    measure: Optional[list[str]] = typer.Option(
        None,
        "--measure",
        "-m",
        help="What to work out (repeatable): 'count' (records, the default), or "
        "'filled', 'distinct', 'min', 'max', 'mean' or 'sum' then ':field', "
        "e.g. 'mean:depth'.",
    ),
    where: Optional[list[str]] = typer.Option(
        None, "--where", "-w", help="Only records with field=value; repeatable"
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-q", help="Only records whose values contain this text"
    ),
    within: Optional[str] = typer.Option(
        None, "--within", help="Only records beneath this record (id or prefix)"
    ),
    limit: int = typer.Option(1000, "--limit", "-n", help="The most groups to show"),
    fmt: Optional[str] = typer.Option(
        None,
        "--format",
        "-f",
        help="Print the summary as csv, tsv, json or jsonl instead of a table "
        "(a last row holds the totals).",
    ),
    csv_out: bool = typer.Option(False, "--csv", help="The same as --format csv"),
) -> None:
    """Summarise records: group them by field values and work out counts,
    averages, totals and more over each group.

    The records are those `record find` would list with the same options. A
    date groups by year, month, week or day (one known only to the year keeps
    a group of its own), a date and time in its field's or collection's time
    zone, a number by value or in ranges, a list (tags, links) by each item.
    The last row is the totals over every record, each counted once.
    """
    import tempfile
    from pathlib import Path

    from civex.domain import summary
    from civex.domain.query import RecordQuery
    from civex.domain.tables import check_format
    from civex.services.table_files import write_table

    out_format = "csv" if csv_out else fmt
    ctx = _ctx()
    try:
        if out_format is not None and out_format not in ("csv", "tsv", "json", "jsonl"):
            check_format(out_format)
            raise ValidationError("xlsx can't be printed; use the API to get a file")
        request = summary.SummaryRequest(
            group_by=[summary.parse_group_by(b) for b in by or []],
            measures=[summary.parse_measure(m) for m in measure or ["count"]],
            limit=limit,
        )
        result = ctx.record_svc.summarise(
            RecordQuery(
                dataset=collection,
                schema=schema,
                within=within,
                where=where or [],
                search=search,
            ),
            request,
        )
    except (NotFoundError, ValidationError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    columns, rows = summary.table_of(result)
    if out_format is not None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"summary.{out_format}"
            write_table(path, out_format, columns, [rows])
            typer.echo(path.read_text(encoding="utf-8"), nl=False)
        return

    print_summary(result)


def print_summary(result) -> None:
    """A summary as a table on the terminal, totals last (also `civex view
    show` of a saved analysis)."""
    from civex.domain import summary

    columns, rows = summary.table_of(result)
    table = Table(*columns)
    for i, row in enumerate(rows):
        cells = [
            "" if row.get(c) is None else _summary_cell(row.get(c)) for c in columns
        ]
        if i == len(rows) - 1:
            table.add_section()
            cells = [f"[bold]{c}[/bold]" for c in cells]
        table.add_row(*cells)
    console.print(table)
    if result.truncated:
        console.print(
            f"[warning]Only the first {result.limit} groups are shown; "
            "use --limit for more.[/warning]"
        )
    if result.timezone:
        console.print(f"Dates and times are grouped in {result.timezone}.")


def _summary_cell(value) -> str:
    if isinstance(value, float):
        return f"{value:,.6g}" if not value.is_integer() else f"{value:,.0f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


@app.command("check")
def record_check(
    collection: Optional[str] = typer.Option(
        None, "--in", help="The collection (omit for every collection)"
    ),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Only this kind of record (omit for every kind)"
    ),
    where: Optional[list[str]] = typer.Option(
        None, "--where", "-w", help="Only records with field=value; repeatable"
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-q", help="Only records whose values contain this text"
    ),
    within: Optional[str] = typer.Option(
        None, "--within", help="Only records beneath this record (id or prefix)"
    ),
    issue: Optional[str] = typer.Option(
        None,
        "--issue",
        "-i",
        help="List the records with this issue instead: breaks_rule, blank, "
        "duplicate_key, broken_reference or missing_file.",
    ),
    field: Optional[str] = typer.Option(
        None, "--field", "-f", help="With --issue: only this field's issue"
    ),
    limit: int = typer.Option(
        200, "--limit", "-n", help="With --issue: the most records to list"
    ),
) -> None:
    """Check records for what needs a look: values their field's rules now
    refuse (a rule tightened after they were entered), required fields left
    empty, records sharing a unique key, links to records that are gone and
    files that are nowhere.

    The records are those `record find` would list with the same options.
    Prints one line per kind, field and issue with a count; with --issue,
    lists the records that have it (their ids are what `record set --id`
    takes to put them right). Nothing is changed.
    """
    from civex.domain import quality
    from civex.domain.query import RecordQuery

    ctx = _ctx()
    query = RecordQuery(
        dataset=collection,
        schema=schema,
        within=within,
        where=where or [],
        search=search,
    )
    try:
        if issue is not None:
            found, total = ctx.quality_svc.records_with(
                query, issue, field=field, limit=limit
            )
        else:
            report = ctx.quality_svc.check(query)
    except (NotFoundError, ValidationError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    if issue is not None:
        if not found:
            console.print("[info]No records have that issue.[/info]")
            return
        # One line each, the whole id first: what `record set --id` takes.
        for f in found:
            console.print(
                f"{f.record_id}  {f.record_name or ''}  [dim]{f.message}[/dim]",
                soft_wrap=True,
            )
        if total > len(found):
            console.print(
                f"[warning]{len(found)} of {total} shown; use --limit for more."
                "[/warning]"
            )
        return

    if not report.kinds:
        console.print("[info]No records to check.[/info]")
        return
    table = Table("Kind", "Field", "Issue", "Records", "For example")
    for kind in report.kinds:
        for line in kind.issues:
            example = line.examples[0] if line.examples else None
            table.add_row(
                kind.schema_label,
                line.field_label,
                quality.ISSUES[line.issue].label,
                f"{line.count:,}",
                f"{(example.record_name or example.record_id[:8])}: {example.message}"
                if example
                else "",
            )
    console.print(table)
    if report.issues == 0:
        console.print(
            f"[success]Nothing to look at in {report.records:,} record(s).[/success]"
        )
    else:
        console.print(
            f"{report.records_with_issues:,} of {report.records:,} record(s) have "
            "something to look at. List them with --issue (and --field)."
        )


@app.command("delete")
def record_delete(
    record_id: str = typer.Argument(..., help="Record ID or short prefix"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Clear any reference/reference_list fields pointing at this record "
        "instead of blocking the delete",
    ),
) -> None:
    """Delete a record (and its children) to Recently Deleted.

    Reversible with `civex record restore` within the retention window
    (see `civex trash list`); `civex record purge` deletes permanently.
    """
    if not yes:
        typer.confirm(f"Delete record '{record_id}'?", abort=True)
    ctx = _ctx()
    try:
        ctx.record_svc.delete(record_id, force=force)
        ctx.commit()
        console.print(f"[success]Deleted record '{record_id}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("restore")
def record_restore(
    record_id: str = typer.Argument(..., help="Record ID or short prefix"),
    only_this: bool = typer.Option(
        False,
        "--only-this",
        help="Restore just this record, not the children deleted with it.",
    ),
    with_parents: bool = typer.Option(
        False,
        "--with-parents",
        help="If deleted records above it hold it back, restore them too, each "
        "by itself, leaving their other children deleted.",
    ),
) -> None:
    """Restore a soft-deleted record (and the children cascade-deleted with it)."""
    ctx = _ctx()
    try:
        ctx.record_svc.restore(
            record_id, only_this=only_this, with_parents=with_parents
        )
        ctx.commit()
        console.print(f"[success]Restored record '{record_id}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("orphans")
def record_orphans(
    limit: int = typer.Option(200, help="Show at most this many."),
) -> None:
    """List live records that sit under a deleted record, so nothing above them
    lists them, with what they sit under. Put one back in place with
    `civex record restore-above <id>`, or delete it."""
    ctx = _ctx()
    try:
        found, total = ctx.record_svc.orphans(limit)
    finally:
        ctx.close()
    if not total:
        console.print("No record sits under a deleted one.")
        return
    table = Table(title=f"{total} record(s) under a deleted record")
    table.add_column("Record")
    table.add_column("Under (deleted)")
    for o in found:
        table.add_row(
            f"{o.record.schema_name} {o.record.natural_name or ''} "
            f"[dim]{str(o.record.id)[:8]}[/dim]",
            " › ".join(
                f"{a.schema_name} {a.natural_name or ''} [dim]{str(a.id)[:8]}[/dim]"
                for a in o.above
            ),
        )
    console.print(table)


@app.command("restore-above")
def record_restore_above(
    record_id: str = typer.Argument(..., help="Record ID or short prefix"),
) -> None:
    """Bring back what a live record sits under that is deleted: each deleted
    record directly above it, by itself, so their other children stay deleted."""
    ctx = _ctx()
    try:
        restored = ctx.record_svc.restore_above(record_id)
        ctx.commit()
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    names = ", ".join(
        f"{r.schema_name} {r.natural_name or str(r.id)[:8]}" for r in restored
    )
    console.print(f"[success]Restored {names}.[/success]")


@app.command("purge")
def record_purge(
    record_id: str = typer.Argument(..., help="Record ID or short prefix"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Permanently delete a record that's already in Recently Deleted. Irreversible."""
    if not yes:
        typer.confirm(
            f"Permanently delete record '{record_id}'? This cannot be undone.",
            abort=True,
        )
    ctx = _ctx()
    try:
        ctx.record_svc.purge(record_id)
        ctx.commit()
        console.print(f"[success]Permanently deleted record '{record_id}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


def _print_move_plan(plan) -> None:
    where = f"'{plan.collection}'" + (
        f" inside '{plan.parent_name}'" if plan.parent_name else ""
    )
    console.print(
        f"{plan.roots} record(s) chosen, {plan.records} with everything inside "
        f"them, would move to {where}"
        + (f" from {', '.join(repr(s) for s in plan.sources)}" if plan.sources else "")
        + "."
    )
    if plan.skipped:
        console.print(f"{plan.skipped} already there, left as they are.")
    for problem in plan.problems:
        console.print(f"[error]{problem}[/error]")


def _move(
    *, to: str, under: Optional[str], dry_run: bool, ids=None, query=None
) -> None:
    ctx = _ctx()
    try:
        if dry_run:
            plan = ctx.record_svc.plan_move(to, under, ids=ids, query=query)
            _print_move_plan(plan)
            if not plan.can_move:
                raise typer.Exit(1)
            return
        result = ctx.record_svc.move(to, under, ids=ids, query=query)
        ctx.commit()
        console.print(
            f"[success]Moved {result.roots} record(s), {result.records} with "
            f"everything inside them, to '{result.collection}'.[/success]"
        )
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("move")
def record_move(
    record_ids: list[str] = typer.Argument(
        ...,
        help="Records to move (ids or unique prefixes), with everything inside them",
    ),
    to: str = typer.Option(..., "--to", help="The collection to move them to"),
    under: Optional[str] = typer.Option(
        None,
        "--under",
        help="The record in that collection they go inside (omit for its top level)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Say what would move and what is in the way, only"
    ),
) -> None:
    """Move records to another collection, or inside another record.

    A record keeps its id, its values and its history, and takes everything
    beneath it along; the move is one event in Activity. It is refused whole
    when a reference would break (a record may only reference its own
    collection's records or a global collection's), a uniqueness key is taken
    where it would land, or its kind can't sit there.
    """
    _move(to=to, under=under, dry_run=dry_run, ids=record_ids)


@app.command("move-all")
def record_move_all(
    dataset_name: str = typer.Argument(..., help="Collection to move records from"),
    to: str = typer.Option(..., "--to", help="The collection to move them to"),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Only records of this schema"
    ),
    under: Optional[str] = typer.Option(
        None,
        "--under",
        help="The record in that collection they go inside (omit for its top level)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Say what would move and what is in the way, only"
    ),
) -> None:
    """Move every record of a collection (or of one schema in it) to another."""
    from civex.domain.query import RecordQuery

    query = RecordQuery(dataset=dataset_name, schema=schema)
    if not yes and not dry_run:
        target = f"all '{schema}' records" if schema else "ALL records"
        typer.confirm(f"Move {target} from '{dataset_name}' to '{to}'?", abort=True)
    _move(to=to, under=under, dry_run=dry_run, query=query)


def _print_bulk_edit(plan) -> None:
    console.print(
        f"{plan.records} record(s) chosen: {plan.changing} would change, "
        f"{plan.unchanged} already hold the value(s), {plan.skipped} can't."
    )
    for skip in plan.skipped_records:
        name = skip.name or str(skip.record_id)[:8]
        console.print(f"  [warning]{name}[/warning]: {skip.reason}")
    if plan.skipped > len(plan.skipped_records):
        console.print(f"  ...and {plan.skipped - len(plan.skipped_records)} more.")
    if plan.runs:
        console.print(
            f"{plan.runs} workflow run(s) would start ({', '.join(plan.workflows)})."
        )
    elif plan.automation_paused:
        console.print("Automation is paused: no workflow runs would start.")


def _typed_changes(ctx, assignments: list[str], schema_name: str) -> dict:
    """`field=value` terms as the values the fields hold: each read as its
    field's type (`coerce_value`), an empty value clearing the field. A
    datetime stays as written, so each record reads it in its own
    collection's zone."""
    fields = {
        rf.field.name: rf.field
        for rf in ctx.record_svc.get_resolved_fields(schema_name)
    }
    changes: dict = {}
    for term in assignments:
        if "=" not in term:
            raise ValidationError(f"'{term}' is not field=value")
        name, _, raw = term.partition("=")
        name = name.strip()
        field = fields.get(name)
        if field is None:
            raise ValidationError(f"'{schema_name}' has no field '{name}' of its own")
        if raw == "":
            changes[name] = None
        elif field.dtype == "datetime":
            changes[name] = raw
        else:
            changes[name] = ctx.record_svc.coerce_value(
                raw, field.dtype, name, field.restrictions
            )
    return changes


@app.command("set")
def record_set(
    assignments: list[str] = typer.Argument(
        ...,
        help="field=value terms; an empty value (field=) clears the field",
    ),
    record_ids: Optional[list[str]] = typer.Option(
        None, "--id", help="A record to edit (id or prefix); repeat for several"
    ),
    collection: Optional[str] = typer.Option(
        None, "--in", help="Edit every record this collection lists (with the filters)"
    ),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Only records of this schema"
    ),
    where: Optional[list[str]] = typer.Option(
        None, "--where", "-w", help="Only records with field=value; repeatable"
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-q", help="Only records whose values contain this text"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Say what would change and what can't, only"
    ),
) -> None:
    """Set (or clear) fields on many records at once.

    Choose the records with --id (repeatable), or with --in and the same
    filters as listing them. Each value is read as its field's type. A record
    takes every change or none: one that can't (a value its field won't take,
    a uniqueness key already used, a field it hasn't got of its own) is left as
    it is and named, and the others are changed. The plan is shown first; the
    edit is one event in Activity, and may start workflow runs that watch the
    fields.
    """
    from civex.domain.query import RecordQuery

    if bool(record_ids) == bool(collection):
        console.print("[error]Choose the records: --id, or --in a collection.[/error]")
        raise typer.Exit(1)
    ctx = _ctx()
    try:
        query = (
            RecordQuery(
                dataset=collection, schema=schema, where=where or [], search=search
            )
            if collection
            else None
        )
        kind = schema or (
            ctx.record_svc.get(record_ids[0]).schema_name if record_ids else None
        )
        if kind is None:
            raise ValidationError(
                "Choose the kind of record with --schema, so each value can be "
                "read as its field's type"
            )
        changes = _typed_changes(ctx, assignments, kind)
        selection = {"ids": record_ids} if record_ids else {"query": query}
        plan = ctx.record_svc.plan_bulk_edit(changes, **selection)
        _print_bulk_edit(plan)
        if dry_run or not plan.can_apply:
            # Nothing to do is fine; nothing that *could* be done is not.
            raise typer.Exit(1 if plan.skipped and not plan.changing else 0)
        if not yes:
            typer.confirm(f"Change {plan.changing} record(s)?", abort=True)
        result = ctx.record_svc.bulk_edit(changes, **selection)
        ctx.commit()
        console.print(
            f"[success]Changed {result.changed} record(s)."
            + (f" {result.skipped} left as they were." if result.skipped else "")
            + "[/success]"
        )
        if result.runs:
            drain_jobs(ctx)
    except (NotFoundError, ValidationError, CoercionError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("delete-all")
def record_delete_all(
    dataset_name: str = typer.Argument(..., help="Dataset to delete records from"),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Limit to this schema"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Clear any reference/reference_list fields pointing at deleted records "
        "instead of blocking the delete",
    ),
) -> None:
    """Delete all records in a dataset (optionally filtered by schema)."""
    target = f"all '{schema}' records" if schema else "ALL records"
    if not yes:
        typer.confirm(f"Delete {target} in dataset '{dataset_name}'?", abort=True)
    ctx = _ctx()
    try:
        deleted = ctx.record_svc.delete_all(
            dataset_name, schema_name=schema, force=force
        )
        ctx.commit()
        console.print(
            f"[success]Deleted {deleted} record(s) from '{dataset_name}'.[/success]"
        )
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("review")
def record_review(
    status: str = typer.Argument(
        ..., help="needs_check, checked, or none to clear the review"
    ),
    record_ids: Optional[list[str]] = typer.Option(
        None, "--id", help="A record to mark (id or prefix); repeat for several"
    ),
    collection: Optional[str] = typer.Option(
        None, "--in", help="Mark every record this collection lists (with the filters)"
    ),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s", help="Only records of this schema"
    ),
    where: Optional[list[str]] = typer.Option(
        None, "--where", "-w", help="Only records with field=value; repeatable"
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-q", help="Only records whose values contain this text"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Say how many would change, only"
    ),
) -> None:
    """Mark records as needing a check, checked, or not reviewed.

    Choose the records with --id (repeatable), or with --in and the same
    filters as listing them. The review is recorded as you, now; records that
    already have the status are left as they are. It is not an edit of the
    records' values (no workflow starts), is in their history, and syncs.
    """
    from civex.domain.query import RecordQuery
    from civex.domain.review import LABELS

    if bool(record_ids) == bool(collection):
        console.print("[error]Choose the records: --id, or --in a collection.[/error]")
        raise typer.Exit(1)
    ctx = _ctx()
    try:
        selection = (
            {"ids": record_ids}
            if record_ids
            else {
                "query": RecordQuery(
                    dataset=collection, schema=schema, where=where or [], search=search
                )
            }
        )
        result = ctx.record_svc.set_review(status, dry_run=dry_run, **selection)
        if not dry_run:
            ctx.commit()
        verb = "Would mark" if dry_run else "Marked"
        console.print(
            f"[success]{verb} {result.changed} record(s) '{LABELS[status]}'."
            + (f" {result.unchanged} already were." if result.unchanged else "")
            + "[/success]"
        )
    except (NotFoundError, ValidationError, ValueError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


note_app = typer.Typer(help="Notes left on records")
app.add_typer(note_app, name="note")


def _print_notes(notes) -> None:
    table = Table(show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("By")
    table.add_column("When")
    table.add_column("Note")
    table.add_column("Resolved")
    for n in notes:
        table.add_row(
            str(n.id)[:8],
            n.author or "",
            n.created_at.strftime("%Y-%m-%d %H:%M"),
            n.body,
            f"by {n.resolved_by or '?'}" if n.resolved_at else "",
        )
    console.print(table)


@note_app.command("add")
def note_add(
    record_id: str = typer.Argument(..., help="The record (id or prefix)"),
    body: str = typer.Argument(..., help="The note's text"),
) -> None:
    """Leave a note on a record, as you."""
    ctx = _ctx()
    try:
        note = ctx.note_svc.add(record_id, body)
        ctx.commit()
        console.print(f"[success]Note {str(note.id)[:8]} added.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@note_app.command("list")
def note_list(
    record_id: str = typer.Argument(..., help="The record (id or prefix)"),
    open_only: bool = typer.Option(False, "--open", help="Only notes not yet resolved"),
) -> None:
    """List a record's notes, oldest first."""
    ctx = _ctx()
    try:
        notes = ctx.note_svc.notes(record_id, include_resolved=not open_only)
        if not notes:
            console.print("No notes.")
            return
        _print_notes(notes)
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@note_app.command("edit")
def note_edit(
    note_id: str = typer.Argument(..., help="The note (id or prefix)"),
    body: str = typer.Argument(..., help="Its new text"),
) -> None:
    """Change the words of a note you wrote."""
    ctx = _ctx()
    try:
        ctx.note_svc.edit(note_id, body)
        ctx.commit()
        console.print("[success]Note changed.[/success]")
    except (NotFoundError, ValidationError, NotAllowedError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@note_app.command("resolve")
def note_resolve(
    note_id: str = typer.Argument(..., help="The note (id or prefix)"),
    reopen: bool = typer.Option(False, "--reopen", help="Open it again instead"),
) -> None:
    """Mark a note resolved (or, with --reopen, open again)."""
    ctx = _ctx()
    try:
        ctx.note_svc.resolve(note_id, resolved=not reopen)
        ctx.commit()
        console.print(
            "[success]Note opened again.[/success]"
            if reopen
            else "[success]Note resolved.[/success]"
        )
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@note_app.command("delete")
def note_delete(
    note_id: str = typer.Argument(..., help="The note (id or prefix)"),
) -> None:
    """Delete a note. It stays in history, and `note restore` brings it back."""
    ctx = _ctx()
    try:
        ctx.note_svc.delete(note_id)
        ctx.commit()
        console.print("[success]Note deleted.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@note_app.command("restore")
def note_restore(
    note_id: str = typer.Argument(..., help="The note (id or prefix)"),
) -> None:
    """Bring back a deleted note."""
    ctx = _ctx()
    try:
        ctx.note_svc.restore(note_id)
        ctx.commit()
        console.print("[success]Note restored.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
