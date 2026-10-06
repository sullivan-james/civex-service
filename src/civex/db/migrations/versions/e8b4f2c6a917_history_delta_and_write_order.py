"""history: room for entries that store only what changed, and the order they were written

Structure only: nothing already in `audit_log` is rewritten here, because this
runs when a project is first opened and a large history would make that open
hang. Existing entries keep both snapshots (`format` 1) and are converted later,
in the background.

- `audit_log.delta`: for an entry that stores only what changed (`format` 2),
  `{path: {"before": ..., "after": ...}}` with `path` an attribute or
  `data.<field id>` (a side is left out where the value was absent).
- `audit_log.format`: 1 = full `old_data`/`new_data` snapshots, 2 = `delta`.
- `audit_log.local_seq`: the order entries were written on this machine,
  numbered by the database itself so no write path can forget it (a sequence
  on PostgreSQL, a trigger on SQLite). Changes are sent in this order; a wall
  clock can step back, and SQLite's `rowid` doesn't exist on PostgreSQL.
  Entries from before have none and go first, in the order of their times.
- `sync_meta.feed_floor`: an authority's oldest numbered entry still kept, so a
  device that has fallen further behind knows to copy again, not skip.
- `sync_meta.history_from`: on a device, where its own copy of the history
  starts (it was cloned at that number; older history is the authority's).

Note for later migrations: a batch rebuild of `audit_log` on SQLite drops the
trigger, so one must create it again.

Revision ID: e8b4f2c6a917
Revises: d6c2a8f41b07
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8b4f2c6a917"
down_revision: Union[str, None] = "d6c2a8f41b07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(
    sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)

_SQLITE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS audit_log_local_seq
AFTER INSERT ON audit_log
FOR EACH ROW WHEN NEW.local_seq IS NULL
BEGIN
    UPDATE audit_log SET local_seq = NEW.rowid WHERE rowid = NEW.rowid;
END
"""


def upgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)
    audit = {c["name"] for c in inspector.get_columns("audit_log")}
    meta = {c["name"] for c in inspector.get_columns("sync_meta")}

    # Plain ADD COLUMN, never a batch rebuild: audit_log is the largest table a
    # project has, and none of these needs one.
    if "delta" not in audit:
        op.add_column("audit_log", sa.Column("delta", _JSON, nullable=True))
    if "format" not in audit:
        op.add_column(
            "audit_log",
            sa.Column("format", sa.SmallInteger(), nullable=False, server_default="1"),
        )
    if "local_seq" not in audit:
        op.add_column(
            "audit_log", sa.Column("local_seq", sa.BigInteger(), nullable=True)
        )
        if postgres:
            # The default is set after the column exists, so only new rows
            # take a number: a volatile default on ADD COLUMN would rewrite
            # every existing row.
            op.execute("CREATE SEQUENCE IF NOT EXISTS audit_log_local_seq")
            op.execute(
                "ALTER TABLE audit_log ALTER COLUMN local_seq "
                "SET DEFAULT nextval('audit_log_local_seq')"
            )
    if not postgres:
        op.execute(_SQLITE_TRIGGER)

    if "feed_floor" not in meta:
        op.add_column(
            "sync_meta",
            sa.Column(
                "feed_floor", sa.BigInteger(), nullable=False, server_default="0"
            ),
        )
    if "history_from" not in meta:
        op.add_column(
            "sync_meta", sa.Column("history_from", sa.BigInteger(), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("ALTER TABLE audit_log ALTER COLUMN local_seq DROP DEFAULT")
    else:
        op.execute("DROP TRIGGER IF EXISTS audit_log_local_seq")
    with op.batch_alter_table("sync_meta") as batch:
        batch.drop_column("history_from")
        batch.drop_column("feed_floor")
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_column("local_seq")
        batch.drop_column("format")
        batch.drop_column("delta")
    if postgres:
        op.execute("DROP SEQUENCE IF EXISTS audit_log_local_seq")
