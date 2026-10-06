"""export_definitions: a table beside the files, or instead of them

An export can now also make a table (csv, tsv, xlsx, json, jsonl) of the records
whose files it takes, with the columns chosen, or make the table alone.

Revision ID: e1a7c5b8f204
Revises: d9f3b1c7e4a2
Create Date: 2026-10-08 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "e1a7c5b8f204"
down_revision: Union[str, None] = "d9f3b1c7e4a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("export_definitions")
    }
    with op.batch_alter_table("export_definitions") as batch:
        if "include_files" not in columns:
            batch.add_column(
                sa.Column(
                    "include_files",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )
        if "table" not in columns:
            batch.add_column(sa.Column("table", civex.db.models._JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("export_definitions") as batch:
        batch.drop_column("table")
        batch.drop_column("include_files")
