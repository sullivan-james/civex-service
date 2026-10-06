"""export_definitions: exports saved with a schema

An export is defined against a schema, like its fields and naming: the kind of
record that holds the files, which file fields, a filter, and a layout. It is run
on a collection or within a record, so neither is stored.

Revision ID: d9f3b1c7e4a2
Revises: c8e2a4f6d913
Create Date: 2026-10-07 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "d9f3b1c7e4a2"
down_revision: Union[str, None] = "c8e2a4f6d913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "export_definitions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "export_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("schema_id", sa.Uuid(), sa.ForeignKey("schemas.id"), nullable=False),
        sa.Column(
            "holder_schema_id", sa.Uuid(), sa.ForeignKey("schemas.id"), nullable=True
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("fields", civex.db.models._JSON, nullable=False),
        sa.Column("filter_tree", civex.db.models._JSON, nullable=True),
        sa.Column(
            "files_layout",
            sa.String(length=10),
            nullable=False,
            server_default="tree",
        ),
        sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        sa.UniqueConstraint("schema_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("export_definitions")
