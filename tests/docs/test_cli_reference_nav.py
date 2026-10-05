"""Every visible sub-app must have a nav entry in mkdocs.yml.

docs/_gen/cli_reference.py generates one page per sub-app from the live Typer
app, so pages appear automatically -- but mkdocs.yml's nav is hand-written.
Without this check, adding a new `app.add_typer(...)` silently produces a page
that builds into the site and is search-indexed but is unreachable from
navigation. `mkdocs build --strict` does not catch it: an unlisted page is an
INFO, not a warning.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer.main

from civex.main import app as cli_app

REPO_ROOT = Path(__file__).resolve().parents[2]
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"


def _nav_cli_pages() -> set[str]:
    """Page stems under reference/cli/ referenced by mkdocs.yml's nav.

    Parsed with a regex rather than yaml.safe_load because mkdocs.yml uses
    tags/constructors that a plain SafeLoader rejects.
    """
    text = MKDOCS_YML.read_text()
    return set(re.findall(r"reference/cli/([A-Za-z0-9_-]+)\.md", text))


def _visible_groups() -> set[str]:
    root = typer.main.get_command(cli_app)
    return {
        name
        for name, sub in getattr(root, "commands", {}).items()
        if not getattr(sub, "hidden", False) and getattr(sub, "commands", None)
    }


def _visible_bare_commands() -> set[str]:
    root = typer.main.get_command(cli_app)
    return {
        name
        for name, sub in getattr(root, "commands", {}).items()
        if not getattr(sub, "hidden", False) and not getattr(sub, "commands", None)
    }


def test_every_sub_app_has_a_nav_entry() -> None:
    missing = sorted(_visible_groups() - _nav_cli_pages())
    assert not missing, (
        "Sub-apps generate a CLI reference page but have no mkdocs.yml nav entry: "
        + ", ".join(missing)
        + ". Add `- civex <name>: reference/cli/<name>.md` under Reference > CLI."
    )


def test_nav_has_no_entries_for_removed_sub_apps() -> None:
    """The reverse drift: a nav entry whose generated page no longer exists is a
    hard `mkdocs build --strict` failure, so catch it in the test suite first."""
    static_pages = {"index", "top-level"}
    stale = sorted(_nav_cli_pages() - _visible_groups() - static_pages)
    assert not stale, (
        "mkdocs.yml nav references CLI pages that are no longer generated: "
        + ", ".join(stale)
    )


def test_bare_commands_are_covered_by_the_top_level_page() -> None:
    """Bare top-level commands share one page, so they need no nav entry each --
    but the page they live on must be in the nav."""
    assert _visible_bare_commands(), "expected at least one bare top-level command"
    assert "top-level" in _nav_cli_pages(), (
        "reference/cli/top-level.md is missing from the nav; every bare "
        "top-level command is documented there and would be unreachable."
    )


def test_generator_is_registered_with_gen_files() -> None:
    text = MKDOCS_YML.read_text()
    assert "docs/_gen/cli_reference.py" in text, (
        "docs/_gen/cli_reference.py is not listed under the gen-files plugin's "
        "scripts, so no CLI reference pages would be generated at build time."
    )
