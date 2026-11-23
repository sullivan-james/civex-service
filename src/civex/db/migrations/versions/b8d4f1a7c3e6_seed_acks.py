"""seed_acks: what the authority has acknowledged of a first upload

A first upload (seed) that is interrupted resumes where it stopped: each
change it sent that the authority answered is remembered here, and the resumed
upload leaves those out instead of sending the whole project again. Each is
kept with the authority's position when it answered, so an authority found
behind it (restored from a backup) is known to have lost them.

Revision ID: b8d4f1a7c3e6
Revises: f3b8d6a2c9e1
Create Date: 2026-11-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f1a7c3e6"
down_revision: Union[str, None] = "f3b8d6a2c9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `max(audit_log.hlc)` is read whenever a change is stamped; without an
    # index each read scans the whole log. On a partitioned `audit_log`
    # PostgreSQL creates it on every partition.
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("audit_log")}
    if "ix_audit_log_hlc" not in indexes:
        op.create_index("ix_audit_log_hlc", "audit_log", ["hlc"])
    op.create_table(
        "seed_acks",
        sa.Column("entry_id", sa.String(length=36), primary_key=True),
        sa.Column("head_seq", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("seed_acks")
    op.drop_index("ix_audit_log_hlc", table_name="audit_log")
