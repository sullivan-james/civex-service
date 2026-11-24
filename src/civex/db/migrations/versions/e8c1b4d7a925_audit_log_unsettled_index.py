"""audit_log: an index on the changes from the authority not settled yet

Revision ID: e8c1b4d7a925
Revises: c5e2a8d7f1b9
Create Date: 2026-11-24 12:00:00.000000

Partial and almost always empty: "is a held change, or an action still
arriving, waiting?" (asked at every pull) becomes a lookup instead of a scan
of the whole log. On a partitioned `audit_log` PostgreSQL creates it on every
partition.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8c1b4d7a925"
down_revision: Union[str, None] = "c5e2a8d7f1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WHERE = sa.text("apply_state IN ('held', 'arriving', 'arrhold')")


def upgrade() -> None:
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("audit_log")}
    if "ix_audit_log_unsettled" not in indexes:
        op.create_index(
            "ix_audit_log_unsettled",
            "audit_log",
            ["hub_seq"],
            postgresql_where=_WHERE,
            sqlite_where=_WHERE,
        )


def downgrade() -> None:
    op.drop_index("ix_audit_log_unsettled", table_name="audit_log")
