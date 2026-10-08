"""sync: a library of shared workflows and plugins

An authority keeps workflows and plugins that devices publish (`library_items`)
as text, for a person on another computer to install (`domain/library.py`). A
device may publish only once the admin allows it (`sync_devices.may_publish`).

Revision ID: b2d6f8a3c517
Revises: a8c4e2f6b1d9
Create Date: 2026-10-08 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

import civex.db.models

revision: str = "b2d6f8a3c517"
down_revision: Union[str, None] = "a8c4e2f6b1d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "may_publish" not in {c["name"] for c in inspector.get_columns("sync_devices")}:
        with op.batch_alter_table("sync_devices") as batch:
            batch.add_column(
                sa.Column(
                    "may_publish",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
    if "library_items" not in inspector.get_table_names():
        op.create_table(
            "library_items",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(200), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("provides", sa.String(200), nullable=True),
            sa.Column("needs", _JSON, nullable=False),
            sa.Column("triggers", _JSON, nullable=False),
            sa.Column("published_by", sa.String(100), nullable=True),
            sa.Column("published_at", civex.db.models._UTCDateTime(), nullable=False),
            sa.UniqueConstraint("kind", "name", name="uq_library_items_kind_name"),
        )


def downgrade() -> None:
    op.drop_table("library_items")
    with op.batch_alter_table("sync_devices") as batch:
        batch.drop_column("may_publish")
