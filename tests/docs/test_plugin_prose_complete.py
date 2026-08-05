"""Every registered builtin plugin needs prose at docs/_prose/plugins/<slug>.md
for docs/_gen/plugin_reference.py to splice its generated tables into — a
builtin shipped without prose would otherwise fail silently at doc build time
(FileNotFoundError deep in mkdocs-gen-files), and a deleted builtin would
leave an orphaned prose file nothing ever reads.
"""

from __future__ import annotations

from pathlib import Path

from civex.plugins import builtins, registry
from civex.plugins.base import PluginTier

PROSE_DIR = Path(__file__).resolve().parents[2] / "docs" / "_prose" / "plugins"
MARKER = "<!-- civex:tables -->"


def _registered_builtin_slugs() -> set[str]:
    registry.discover_plugins(builtins)
    return {
        pid.removeprefix("civex.")
        for pid, reg in registry.all_plugins().items()
        if reg.tier == PluginTier.BUILTIN
    }


def test_prose_files_match_registered_plugins() -> None:
    prose_slugs = {path.stem for path in PROSE_DIR.glob("*.md")}
    assert prose_slugs == _registered_builtin_slugs()


def test_every_prose_file_has_tables_marker() -> None:
    for path in PROSE_DIR.glob("*.md"):
        assert MARKER in path.read_text(), f"{path} is missing {MARKER}"
