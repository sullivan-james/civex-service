"""collection scope and schema lists

Adds `datasets.scope` ('local' | 'global') and the `dataset_schemas` link
table (which schemas a collection is for).

Every existing collection becomes 'local'. Its schema list is backfilled with
the schemas its live records already use, plus their ancestors (a child
record's parent lives in the same collection), so a project keeps working
once record creation is checked against the list.

Revision ID: 9b4d2f6e8a13
Revises: 7c2e9d4a1b58
Create Date: 2026-10-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9b4d2f6e8a13"
down_revision: Union[str, None] = "7c2e9d4a1b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "scope",
                sa.String(length=10),
                nullable=False,
                server_default="local",
            )
        )
        batch_op.create_check_constraint(
            "ck_datasets_scope", "scope IN ('local', 'global')"
        )

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

    # Backfill: schemas already in use, then their ancestors, to a fixpoint.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO dataset_schemas (dataset_id, schema_id) "
            "SELECT DISTINCT dataset_id, schema_id FROM records"
        )
    )
    while True:
        added = bind.execute(
            sa.text(
                "INSERT INTO dataset_schemas (dataset_id, schema_id) "
                "SELECT DISTINCT ds.dataset_id, s.parent_id "
                "FROM dataset_schemas ds JOIN schemas s ON s.id = ds.schema_id "
                "WHERE s.parent_id IS NOT NULL AND NOT EXISTS ("
                "  SELECT 1 FROM dataset_schemas x "
                "  WHERE x.dataset_id = ds.dataset_id AND x.schema_id = s.parent_id)"
            )
        ).rowcount
        if not added:
            break


def downgrade() -> None:
    op.drop_index("ix_dataset_schemas_schema", table_name="dataset_schemas")
    op.drop_table("dataset_schemas")
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.drop_constraint("ck_datasets_scope", type_="check")
        batch_op.drop_column("scope")
