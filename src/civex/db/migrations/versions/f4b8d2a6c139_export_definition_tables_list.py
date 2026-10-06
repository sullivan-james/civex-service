"""export_definitions: several tables, each placed where it is wanted

An export took one table (`table`: format and columns). It now takes a list
(`tables`), each saying what its rows are, where it is written and its columns,
so an export can make a table per recording, a metadata sheet per selection, and
so on. A saved table becomes the one entry of the list.

Revision ID: f4b8d2a6c139
Revises: e1a7c5b8f204
Create Date: 2026-10-09 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import civex.db.models

revision: str = "f4b8d2a6c139"
down_revision: Union[str, None] = "e1a7c5b8f204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = civex.db.models._JSON


def upgrade() -> None:
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("export_definitions")
    }
    if "tables" not in columns:
        with op.batch_alter_table("export_definitions") as batch:
            batch.add_column(sa.Column("tables", _JSON, nullable=True))
    if "table" in columns:
        defs = sa.table(
            "export_definitions",
            sa.column("id", sa.Uuid()),
            sa.column("table", _JSON),
            sa.column("tables", _JSON),
        )
        bind = op.get_bind()
        for row in bind.execute(sa.select(defs.c.id, defs.c.table)).all():
            bind.execute(
                sa.update(defs)
                .where(defs.c.id == row.id)
                .values(tables=[row.table] if row.table else [])
            )
        with op.batch_alter_table("export_definitions") as batch:
            batch.drop_column("table")


def downgrade() -> None:
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("export_definitions")
    }
    if "table" not in columns:
        with op.batch_alter_table("export_definitions") as batch:
            batch.add_column(sa.Column("table", _JSON, nullable=True))
    defs = sa.table(
        "export_definitions",
        sa.column("id", sa.Uuid()),
        sa.column("table", _JSON),
        sa.column("tables", _JSON),
    )
    bind = op.get_bind()
    for row in bind.execute(sa.select(defs.c.id, defs.c.tables)).all():
        first = (row.tables or [None])[0]
        bind.execute(
            sa.update(defs)
            .where(defs.c.id == row.id)
            .values(table=first if first is not None else sa.null())
        )
    with op.batch_alter_table("export_definitions") as batch:
        batch.drop_column("tables")
