"""A migration's parent never changes once it is committed.

A database records only the revision it reached. Moving a migration that has
already run somewhere to a new place in the chain (giving it, or one after
it, another parent) leaves that database stamped past migrations it never
ran: it looks current and fails when the missing table or column is used.
Two migrations made side by side are joined with a merge migration instead.
`migration_parents.json` records every migration's parent; a new migration
adds a line there, and no existing line may change."""

from __future__ import annotations

import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_RECORDED = Path(__file__).parent / "migration_parents.json"


def _parents() -> dict[str, object]:
    cfg = Config()
    cfg.set_main_option(
        "script_location",
        str(Path(__file__).parents[2] / "src" / "civex" / "db" / "migrations"),
    )
    out: dict[str, object] = {}
    for rev in ScriptDirectory.from_config(cfg).walk_revisions():
        down = rev.down_revision
        out[rev.revision] = sorted(down) if isinstance(down, tuple) else down
    return out


def test_no_committed_migration_changes_its_parent():
    recorded = json.loads(_RECORDED.read_text())
    now = _parents()
    changed = {
        rev: (was, now.get(rev))
        for rev, was in recorded.items()
        if now.get(rev, "<removed>") != was
    }
    assert not changed, (
        f"These migrations' parents changed (recorded, now): {changed}. A "
        "database that already ran them would be stamped past migrations it "
        "never ran. Put the parents back and add a merge migration instead."
    )


def test_every_migration_is_recorded():
    new = sorted(set(_parents()) - set(json.loads(_RECORDED.read_text())))
    assert not new, (
        f"Record the parent of each new migration in {_RECORDED.name}: {new}"
    )
