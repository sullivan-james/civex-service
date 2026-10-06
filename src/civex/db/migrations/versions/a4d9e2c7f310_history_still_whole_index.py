"""history: an index of the edits still stored whole, for their conversion

Converting history written before deltas (`HistoryCompactionService`) picks a
batch of the edits still stored whole and counts what is left. Without an index
both read the whole history table each time, which on a large project is
minutes of disk per batch (and the count runs whenever the app asks how far it
has got). This partial index holds exactly those entries, so both touch only
what is left, and once everything is converted it is empty.

Structure only (building it reads the table once).

Revision ID: a4d9e2c7f310
Revises: f1c3a5e7b902
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4d9e2c7f310"
down_revision: Union[str, None] = "f1c3a5e7b902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WHERE = "format = 1 AND action IN ('update', 'restore')"


def upgrade() -> None:
    have = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("audit_log")}
    if "ix_audit_log_still_whole" not in have:
        op.create_index(
            "ix_audit_log_still_whole",
            "audit_log",
            ["id"],
            sqlite_where=sa.text(_WHERE),
            postgresql_where=sa.text(_WHERE),
        )


def downgrade() -> None:
    op.drop_index("ix_audit_log_still_whole", table_name="audit_log")
