"""audit_log: an index on the changes a first upload has set aside

Revision ID: f3b8d6a2c9e1
Revises: d9e3a5c7f1b4
Create Date: 2026-11-23 12:00:00.000000

Partial and almost always empty, so it costs nothing to keep and makes
"is a first upload unfinished?" (asked on every status read and every sync)
a lookup instead of a scan of the whole log. On a partitioned `audit_log`
PostgreSQL creates it on every partition.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d6a2c9e1"
down_revision: Union[str, None] = "d9e3a5c7f1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("audit_log")}
    if "ix_audit_log_seeding" not in indexes:
        op.create_index(
            "ix_audit_log_seeding",
            "audit_log",
            ["timestamp"],
            postgresql_where=sa.text("sync_state = 'seeding'"),
            sqlite_where=sa.text("sync_state = 'seeding'"),
        )


def downgrade() -> None:
    op.drop_index("ix_audit_log_seeding", table_name="audit_log")
