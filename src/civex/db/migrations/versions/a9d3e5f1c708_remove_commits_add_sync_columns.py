"""remove commits; give audit_log its sync columns

The old push/pull sync grouped audit entries into `commits` (`seq`,
`pushed_at`). That sync is gone, and a commit was never something a person saw
or chose, so `commits` and `audit_log.commit_id` (with the two indexes on it)
are dropped. The partial "staged" index went with it: there is no staging.

The same rebuild of `audit_log` adds the columns sync will need (`actor`,
`device_id`, `hlc`, `hub_seq`, `sync_state`), nothing writes them yet. They
are added now so a large table is rebuilt once on a customer's machine, not
twice. Existing entries become `sync_state = 'pending'`, which has no effect
until a remote is set.

The downgrade recreates an empty `commits` table: which commit an entry
belonged to is not recoverable.

Revision ID: a9d3e5f1c708
Revises: f2a6c8d1e093
Create Date: 2026-10-05 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "a9d3e5f1c708"
down_revision: Union[str, None] = "f2a6c8d1e093"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("audit_log")}
    indexes = {i["name"] for i in inspector.get_indexes("audit_log")}

    # Indexes first: SQLite can't rebuild a table around an index on a column
    # that is going away.
    for name in ("ix_audit_log_staged", "ix_audit_log_commit"):
        if name in indexes:
            op.drop_index(name, table_name="audit_log")

    with op.batch_alter_table("audit_log") as batch:
        if "commit_id" in columns:
            batch.drop_column("commit_id")  # its foreign key goes with it
        if "actor" not in columns:
            batch.add_column(sa.Column("actor", sa.String(100), nullable=True))
        if "device_id" not in columns:
            batch.add_column(sa.Column("device_id", sa.Uuid(), nullable=True))
        if "hlc" not in columns:
            batch.add_column(sa.Column("hlc", sa.String(40), nullable=True))
        if "hub_seq" not in columns:
            batch.add_column(sa.Column("hub_seq", sa.BigInteger(), nullable=True))
        if "sync_state" not in columns:
            batch.add_column(
                sa.Column(
                    "sync_state",
                    sa.String(10),
                    nullable=False,
                    server_default="pending",
                )
            )

    if "commits" in inspector.get_table_names():
        op.drop_table("commits")


def downgrade() -> None:
    op.create_table(
        "commits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(length=1000), nullable=True),
        sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("schema_count", sa.Integer(), nullable=False),
        sa.Column("dataset_count", sa.Integer(), nullable=False),
        sa.Column("pushed_at", civex.db.models._UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_column("sync_state")
        batch.drop_column("hub_seq")
        batch.drop_column("hlc")
        batch.drop_column("device_id")
        batch.drop_column("actor")
        batch.add_column(sa.Column("commit_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_audit_log_commit", "commits", ["commit_id"], ["id"]
        )
    op.create_index("ix_audit_log_commit", "audit_log", ["commit_id"])
    op.create_index(
        "ix_audit_log_staged",
        "audit_log",
        ["timestamp"],
        postgresql_where=sa.text("commit_id IS NULL"),
        sqlite_where=sa.text("commit_id IS NULL"),
    )
