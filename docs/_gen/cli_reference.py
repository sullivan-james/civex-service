"""Generates docs/reference/cli/*.md from the live Typer app (civex.main:app).

One page per sub-app group (`civex schema`, `civex record`, ...), one page for
the bare top-level commands, and an index listing every command. Hidden
commands are skipped -- the five SSH plumbing commands are documented by hand
in docs/reference/cli/plumbing.md instead.

Why this is a custom generator rather than mkdocs-click or `typer utils docs`:
see docs/contributing/cli-docs-tooling-decision.md. The short version is that
Typer vendors its own Click fork under `typer._click` and does not depend on
the PyPI `click` package, so mkdocs-click's isinstance checks are all False
against this command tree.

Two drift checks back this up: tests/docs/test_cli_options_documented.py
(every visible param has help=) and tests/docs/test_cli_reference_nav.py
(every visible sub-app has a nav entry in mkdocs.yml).
"""

from __future__ import annotations

import re
from typing import Any

import mkdocs_gen_files
import typer.main
import typer._click as tc

from civex.main import app as cli_app

ROOT_NAME = "civex"
OUT_DIR = "reference/cli"

# Top-level commands that aren't groups are collected onto one page, ordered by
# the rich_help_panel they're grouped under in `civex --help` so the docs and
# the terminal tell the same story.
PANEL_ORDER = [
    "Start a working area",
    "Work on the current change",
    "Collaborate",
]
UNPANELLED = "Other"


def visible_subcommands(cmd: Any) -> dict[str, Any]:
    """Non-hidden children, or {} for a leaf. Duck-typed on `.commands` because
    isinstance against the PyPI click package doesn't hold for Typer's fork."""
    return {
        name: sub
        for name, sub in sorted(getattr(cmd, "commands", {}).items())
        if not getattr(sub, "hidden", False)
    }


def is_group(cmd: Any) -> bool:
    return bool(getattr(cmd, "commands", None))


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


def render_help(text: str | None) -> str:
    """Markdown for a command's help string.

    Indented example blocks (the convention in this CLI's docstrings, e.g.
    `schema add-field`'s "Restriction examples:") become fenced code blocks.
    Typer's own markdown emitter relies on `\\b` for these, which under
    rich_markup_mode="rich" passes through as a literal \\x08 and renders as a
    visible glyph -- so we fence instead, and CLAUDE.md forbids `\\b` outright.
    """
    if not text:
        return ""

    out: list[str] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        # Strip the common indent so the fence contents start at column 0.
        indent = min(len(ln) - len(ln.lstrip()) for ln in block if ln.strip())
        out.append("```")
        out.extend(ln[indent:] if ln.strip() else "" for ln in block)
        out.append("```")
        block.clear()

    for line in text.expandtabs(4).splitlines():
        if line.startswith(("  ", "\t")) and line.strip():
            block.append(line)
        else:
            flush()
            out.append(line)
    flush()

    return "\n".join(out).strip() + "\n"


def summary(cmd: Any) -> str:
    """One-line description for index/overview tables."""
    text = getattr(cmd, "short_help", None) or getattr(cmd, "help", "") or ""
    first = text.strip().split("\n\n")[0].replace("\n", " ").strip()
    return cell(first)


def cell(text: str) -> str:
    """Escape characters that would break out of a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


def params_of(cmd: Any, ctx: Any) -> list[Any]:
    return [
        p
        for p in cmd.get_params(ctx)
        if p.name != "help" and not getattr(p, "hidden", False)
    ]


def is_argument(param: Any) -> bool:
    return type(param).__name__.endswith("Argument")


def arg_metavar(param: Any) -> str:
    name = (getattr(param, "metavar", None) or param.name).upper()
    if getattr(param, "nargs", 1) == -1:
        name = f"{name}..."
    return name if param.required else f"[{name}]"


def option_names(param: Any) -> str:
    names = list(getattr(param, "opts", []))
    names += list(getattr(param, "secondary_opts", []))
    return ", ".join(f"`{n}`" for n in names)


def type_name(param: Any) -> str:
    ptype = getattr(param, "type", None)
    choices = getattr(ptype, "choices", None)
    if choices:
        return " \\| ".join(f"`{c}`" for c in choices)
    if getattr(param, "is_flag", False):
        return "flag"
    return f"`{getattr(ptype, 'name', 'text')}`"


def default_str(param: Any) -> str:
    default = param.default
    if default is None or default is ...:
        return ""
    if getattr(param, "is_flag", False):
        # For --required/--optional style pairs, name the side that's on by
        # default -- more useful than printing "False".
        secondary = getattr(param, "secondary_opts", None)
        if secondary:
            on = param.opts[0] if default else secondary[0]
            return f"`{on}`"
        return "`true`" if default else "`false`"
    if default == "":
        return '`""`'
    if isinstance(default, (list, tuple)):
        return ", ".join(f"`{d}`" for d in default) if default else ""
    return f"`{default}`"


def usage(path: list[str], cmd: Any, ctx: Any) -> str:
    parts = [" ".join(path)]
    if is_group(cmd):
        parts.append("COMMAND [ARGS]...")
        return " ".join(parts)
    if any(not is_argument(p) for p in params_of(cmd, ctx)):
        parts.append("[OPTIONS]")
    parts += [arg_metavar(p) for p in params_of(cmd, ctx) if is_argument(p)]
    return " ".join(parts)


def param_tables(cmd: Any, ctx: Any) -> str:
    params = params_of(cmd, ctx)
    args = [p for p in params if is_argument(p)]
    opts = [p for p in params if not is_argument(p)]
    out = ""

    if args:
        out += "**Arguments**\n\n| Argument | Type | Required | Description |\n|---|---|---|---|\n"
        for p in args:
            out += (
                f"| `{arg_metavar(p).strip('[]')}` | {type_name(p)} "
                f"| {'yes' if p.required else 'no'} | {cell(p.help or '')} |\n"
            )
        out += "\n"

    if opts:
        out += "**Options**\n\n| Option | Type | Default | Description |\n|---|---|---|---|\n"
        for p in opts:
            desc = cell(p.help or "")
            envvar = getattr(p, "envvar", None)
            if envvar:
                desc += f" Env: `{envvar}`."
            required = " **(required)**" if p.required else ""
            out += (
                f"| {option_names(p)} | {type_name(p)} "
                f"| {default_str(p)} | {desc}{required} |\n"
            )
        out += "\n"

    return out


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------


def anchor(path: list[str]) -> str:
    """Match Python-Markdown's slug for a `## \\`civex schema add-field\\`` heading."""
    return re.sub(r"[^a-z0-9]+", "-", " ".join(path).lower()).strip("-")


def render_command(path: list[str], cmd: Any, level: int) -> str:
    ctx = tc.Context(cmd, info_name=" ".join(path))
    out = f"{'#' * level} `{' '.join(path)}`\n\n"
    body = render_help(getattr(cmd, "help", None))
    if body:
        out += body + "\n"
    out += f"**Usage**\n\n```bash\n{usage(path, cmd, ctx)}\n```\n\n"
    out += param_tables(cmd, ctx)
    return out


def render_group_page(name: str, group: Any) -> str:
    path = [ROOT_NAME, name]
    subs = visible_subcommands(group)

    out = f"# `{' '.join(path)}`\n\n"
    body = render_help(getattr(group, "help", None))
    if body:
        out += body + "\n"

    out += "| Command | Description |\n|---|---|\n"
    for sub_name, sub in subs.items():
        out += f"| [`{sub_name}`](#{anchor(path + [sub_name])}) | {summary(sub)} |\n"
    out += "\n"

    for sub_name, sub in subs.items():
        out += render_command(path + [sub_name], sub, level=2)

    return out


def render_top_level_page(commands: dict[str, Any]) -> str:
    by_panel: dict[str, list[tuple[str, Any]]] = {}
    for name, cmd in commands.items():
        panel = getattr(cmd, "rich_help_panel", None) or UNPANELLED
        by_panel.setdefault(panel, []).append((name, cmd))

    ordered = [p for p in PANEL_ORDER if p in by_panel]
    ordered += [p for p in by_panel if p not in PANEL_ORDER]

    out = (
        "# Top-level commands\n\n"
        "Commands invoked directly as `civex <command>`, grouped the same way "
        "`civex --help` groups them.\n\n"
    )
    for panel in ordered:
        out += f"| {panel} | Description |\n|---|---|\n"
        for name, cmd in by_panel[panel]:
            out += f"| [`{name}`](#{anchor([ROOT_NAME, name])}) | {summary(cmd)} |\n"
        out += "\n"

    for panel in ordered:
        for name, cmd in by_panel[panel]:
            out += render_command([ROOT_NAME, name], cmd, level=2)

    return out


def render_index(groups: dict[str, Any], top_level: dict[str, Any]) -> str:
    out = (
        "# CLI reference\n\n"
        "Generated from the `civex` command tree, so it always matches the "
        "installed version. Run any command with `--help` for the same "
        "information in your terminal.\n\n"
        "## Command groups\n\n| Group | Commands | Description |\n|---|---|---|\n"
    )
    for name, group in groups.items():
        subs = visible_subcommands(group)
        out += f"| [`civex {name}`]({name}.md) | {len(subs)} | {summary(group)} |\n"

    out += "\n## Top-level commands\n\n| Command | Description |\n|---|---|\n"
    for name, cmd in top_level.items():
        out += (
            f"| [`civex {name}`](top-level.md#{anchor([ROOT_NAME, name])}) "
            f"| {summary(cmd)} |\n"
        )

    out += (
        "\n## Plumbing\n\nFive hidden commands back the SSH transport and are "
        "not intended for direct use. See [Plumbing commands](plumbing.md).\n"
    )
    return out


# ---------------------------------------------------------------------------

root = typer.main.get_command(cli_app)
children = visible_subcommands(root)
groups = {n: c for n, c in children.items() if is_group(c)}
top_level = {n: c for n, c in children.items() if not is_group(c)}

for group_name, group_cmd in groups.items():
    with mkdocs_gen_files.open(f"{OUT_DIR}/{group_name}.md", "w") as f:
        f.write(render_group_page(group_name, group_cmd))

with mkdocs_gen_files.open(f"{OUT_DIR}/top-level.md", "w") as f:
    f.write(render_top_level_page(top_level))

with mkdocs_gen_files.open(f"{OUT_DIR}/index.md", "w") as f:
    f.write(render_index(groups, top_level))
