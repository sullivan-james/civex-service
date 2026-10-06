"""views.files_layout: how a view's files are arranged when exported

A saved view says which columns, filter and sort make up the data someone needs;
this adds how its files are laid out when exported as a folder or zip: "tree"
(a folder per record above each file, the default) or "flat" (all in one).

Revision ID: c8e2a4f6d913
Revises: a3d8f0b6c125
Create Date: 2026-10-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8e2a4f6d913"
down_revision: Union[str, None] = "a3d8f0b6c125"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("views")}
    if "files_layout" not in columns:
        with op.batch_alter_table("views") as batch:
            batch.add_column(
                sa.Column(
                    "files_layout",
                    sa.String(length=10),
                    nullable=False,
                    server_default="tree",
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("views") as batch:
        batch.drop_column("files_layout")
