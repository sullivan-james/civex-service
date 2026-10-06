"""history: which entries one action wrote, so they are taken or refused together

Some actions write several entries: renaming a field also rewrites the naming
templates that use it, deleting a record deletes everything beneath it. Taken
one at a time by an authority, part of such an action could go in and part not
(a template naming a field that was never renamed). `audit_log.op_id` is shared
by the entries of one action, and an authority settles them as one.

Structure only: existing entries have none (each stands alone).

Revision ID: f1c3a5e7b902
Revises: e8b4f2c6a917
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1c3a5e7b902"
down_revision: Union[str, None] = "e8b4f2c6a917"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("audit_log")}
    if "op_id" not in have:
        # Plain ADD COLUMN: audit_log is large and needs no rebuild for this.
        op.add_column("audit_log", sa.Column("op_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_column("op_id")
    if bind.dialect.name != "postgresql":
        # The batch rebuild drops the write-order trigger; put it back.
        from importlib import import_module

        prior = import_module(
            "civex.db.migrations.versions.e8b4f2c6a917_history_delta_and_write_order"
        )
        op.execute(prior._SQLITE_TRIGGER)
