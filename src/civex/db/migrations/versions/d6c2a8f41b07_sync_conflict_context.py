"""sync conflicts: what the value was, and who wrote the one that stayed

A conflict row held only the two sides. To judge it a person also needs what the
value was before either edit (`base`) and who changed it on the authority and
when (`theirs_actor`, `theirs_at`).

Revision ID: d6c2a8f41b07
Revises: c9e1f4a7b3d2
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import civex.db.models

revision: str = "d6c2a8f41b07"
down_revision: Union[str, None] = "c9e1f4a7b3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(
    sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("sync_conflicts")}
    with op.batch_alter_table("sync_conflicts") as batch:
        if "base" not in have:
            batch.add_column(sa.Column("base", _JSON, nullable=True))
        if "theirs_actor" not in have:
            batch.add_column(sa.Column("theirs_actor", sa.String(100), nullable=True))
        if "theirs_at" not in have:
            batch.add_column(
                sa.Column("theirs_at", civex.db.models._UTCDateTime(), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("sync_conflicts") as batch:
        batch.drop_column("theirs_at")
        batch.drop_column("theirs_actor")
        batch.drop_column("base")
