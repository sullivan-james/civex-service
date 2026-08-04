"""
Plugin commands.
Plugins are the individual steps within a workflow (data sources, transformations, outputs).
Both commands read PluginService.list_registered() -- the same declared contract
(CIVEX-141/144) the API and frontend plugin panel read, so nothing here can drift
from what a workflow author actually gets when they reference a plugin.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table

from civex.cli.utils import get_ctx as _ctx
from civex.console import console

app = typer.Typer(help="Inspect available workflow plugins")


@app.command("list")
def plugin_list() -> None:
    """List registered plugins (built-ins and custom)."""
    ctx = _ctx()
    plugins = ctx.plugin_svc.list_registered()
    if not plugins:
        console.print("[info]No plugins registered.[/info]")
        return

    table = Table("ID", "Name", "Tier", "Category", "Description")
    for p in plugins:
        table.add_row(
            p["id"],
            p["name"],
            "built-in" if p["builtin"] else "user",
            p["category"],
            p["description"] or "",
        )
    console.print(table)


@app.command("info")
def plugin_info(plugin_id: str = typer.Argument(..., help="Plugin ID")) -> None:
    """Show a plugin's inputs, outputs, capabilities, and config schema."""
    ctx = _ctx()
    by_id = {p["id"]: p for p in ctx.plugin_svc.list_registered()}
    plugin = by_id.get(plugin_id)
    if plugin is None:
        console.print(f"[error]Plugin '{plugin_id}' not found.[/error]")
        raise typer.Exit(1)

    console.print(f"[bold]{plugin['name']}[/bold]  [dim]({plugin['id']})[/dim]")
    if plugin["description"]:
        console.print(f"  {plugin['description']}")
    console.print(
        f"  Tier: {'built-in' if plugin['builtin'] else 'user'}  ·  "
        f"Category: {plugin['category']}"
    )
    if plugin["capabilities"]:
        console.print(f"  Capabilities: {', '.join(plugin['capabilities'])}")

    console.print()
    _print_io_section("Inputs", plugin["inputs"])
    console.print()
    _print_io_section("Outputs", plugin["outputs"])
    console.print()
    _print_config_section(plugin["config_schema"])


def _print_io_section(title: str, specs: list[dict] | None) -> None:
    console.print(f"[bold]{title}[/bold]")
    if specs is None:
        console.print("  (not declared)")
        return
    if not specs:
        console.print("  (none)")
        return
    table = Table("Name", "Type", "Required", "Description")
    for spec in specs:
        table.add_row(
            spec["name"],
            spec["type"],
            "yes" if spec["required"] else "",
            spec["description"] or "",
        )
    console.print(table)


def _print_config_section(config_schema: dict[str, Any]) -> None:
    console.print("[bold]Config[/bold]")
    properties = config_schema.get("properties") or {}
    if not properties:
        console.print("  (none)")
        return
    required = set(config_schema.get("required") or [])
    table = Table("Key", "Type", "Required", "Default")
    for key, prop in properties.items():
        table.add_row(
            key,
            str(prop.get("type", "any")),
            "yes" if key in required else "",
            str(prop["default"]) if "default" in prop else "",
        )
    console.print(table)
