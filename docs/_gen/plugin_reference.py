"""Generates docs/reference/plugins/<slug>.md for every registered builtin
plugin by splicing an IOSpec/config table into the hand-written prose at
docs/_prose/plugins/<slug>.md. The per-plugin YAML examples and gotchas in
that prose can't be derived from the plugin declarations, so they're kept
hand-written rather than generated (tests/docs/test_plugin_prose_complete.py
is the drift check that a prose file exists for every registered plugin)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mkdocs_gen_files
from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel

from civex.plugins import builtins, registry
from civex.plugins.registry import PluginRegistration

registry.discover_plugins(builtins)

PROSE_DIR = Path("docs/_prose/plugins")
MARKER = "<!-- civex:tables -->"


def _cell(text: str) -> str:
    """Escape `|` so a description/type containing one (e.g. `output_type`'s
    "string | integer | ...") doesn't get parsed as extra table columns."""
    return text.replace("|", "\\|")


def header(reg: PluginRegistration) -> str:
    capabilities = ", ".join(f"`{c}`" for c in reg.capabilities) or "none"
    return (
        f"**Plugin ID:** `{reg.id}`  \n"
        f"**Category:** `{reg.category}`  \n"
        f"**Capabilities:** {capabilities}\n\n"
    )


def io_table(specs: list[IOSpec] | None, title: str) -> str:
    if not specs:
        return ""
    lines = [
        f"**{title}**\n",
        "| Name | Type | Required | Description |",
        "|---|---|---|---|",
    ]
    for spec in specs:
        lines.append(
            f"| `{spec.name}` | {_cell(spec.type)} | {'yes' if spec.required else 'no'} "
            f"| {_cell(spec.description)} |"
        )
    return "\n".join(lines) + "\n\n"


def _prop_type(prop: dict[str, Any]) -> str:
    if "type" in prop:
        return prop["type"]
    if "anyOf" in prop:
        return " | ".join(sub.get("type", "any") for sub in prop["anyOf"])
    return "any"


def _prop_default(prop: dict[str, Any]) -> str:
    if "default" not in prop:
        return ""
    default = prop["default"]
    if default is None:
        return "null"
    if default == "":
        return '""'
    return str(default)


def config_table(config_model: type[BaseModel]) -> str:
    schema = config_model.model_json_schema(by_alias=True)
    properties = schema.get("properties", {})
    if not properties:
        return ""
    required = set(schema.get("required", []))
    lines = [
        "**Config**\n",
        "| Field | Type | Required | Default | Description |",
        "|---|---|---|---|---|",
    ]
    for name, prop in properties.items():
        lines.append(
            f"| `{name}` | {_cell(_prop_type(prop))} | {'yes' if name in required else 'no'} "
            f"| {_cell(_prop_default(prop))} | {_cell(prop.get('description', ''))} |"
        )
    return "\n".join(lines) + "\n\n"


for pid, reg in sorted(registry.all_plugins().items()):
    slug = pid.removeprefix("civex.")
    prose = (PROSE_DIR / f"{slug}.md").read_text()
    tables = (
        header(reg)
        + config_table(reg.config_model)
        + io_table(reg.inputs, "Inputs")
        + io_table(reg.outputs, "Outputs")
    )
    with mkdocs_gen_files.open(f"reference/plugins/{slug}.md", "w") as f:
        f.write(prose.replace(MARKER, tables))
