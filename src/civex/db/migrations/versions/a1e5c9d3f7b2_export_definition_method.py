"""export_definitions: how the export is made (link, copy or zip) and onto which drive

A saved export said what it takes but not how it is handed over, so every run
asked. It now carries `method` ('link' | 'copy' | 'zip', link by default) and,
for a copy, the `volume` to copy onto (None: the project folder).

Revision ID: a1e5c9d3f7b2
Revises: d2f6a9c4e8b1
Create Date: 2026-10-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1e5c9d3f7b2"
down_revision: Union[str, None] = "d2f6a9c4e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("export_definitions")
    }
    with op.batch_alter_table("export_definitions") as batch:
        if "method" not in columns:
            batch.add_column(
                sa.Column(
                    "method", sa.String(10), nullable=False, server_default="link"
                )
            )
        if "volume" not in columns:
            batch.add_column(sa.Column("volume", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("export_definitions") as batch:
        batch.drop_column("volume")
        batch.drop_column("method")
