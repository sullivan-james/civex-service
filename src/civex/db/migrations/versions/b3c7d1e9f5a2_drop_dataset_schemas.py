"""A collection holds records of every schema: the schema list goes

`dataset_schemas` said which schemas a collection was for, and the app, the
CLI and sync each had to keep it right. A collection now holds records of
every schema, so the table goes, and with it every list, whoever set it.

Revision ID: b3c7d1e9f5a2
Revises: a1e5c9d3f7b2
Create Date: 2026-10-26 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c7d1e9f5a2"
down_revision: Union[str, None] = "a1e5c9d3f7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "dataset_schemas" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_dataset_schemas_schema", table_name="dataset_schemas")
        op.drop_table("dataset_schemas")


def downgrade() -> None:
    op.create_table(
        "dataset_schemas",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schema_id"], ["schemas.id"]),
        sa.PrimaryKeyConstraint("dataset_id", "schema_id"),
    )
    op.create_index(
        "ix_dataset_schemas_schema", "dataset_schemas", ["schema_id"], unique=False
    )
