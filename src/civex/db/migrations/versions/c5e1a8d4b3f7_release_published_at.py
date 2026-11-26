"""releases: when each was published

A host can hold a release back (frozen, but not citable, downloadable or
copyable) and discard it if it was never published. Every release made so far
counts as published when it was created.

Revision ID: c5e1a8d4b3f7
Revises: b7d3e9a1c5f2
Create Date: 2026-11-26 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import civex.db.models

revision: str = "c5e1a8d4b3f7"
down_revision: Union[str, None] = "b7d3e9a1c5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("releases")}
    if "published_at" not in have:
        with op.batch_alter_table("releases") as batch:
            batch.add_column(
                sa.Column("published_at", civex.db.models._UTCDateTime(), nullable=True)
            )
        op.execute("UPDATE releases SET published_at = created_at")


def downgrade() -> None:
    with op.batch_alter_table("releases") as batch:
        batch.drop_column("published_at")
