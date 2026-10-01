"""GIN index on records.search_vector

Search (`search_vector @@ plainto_tsquery(...)`, behind the search box and the
reference pickers) had no index to use on PostgreSQL, so every search read
every record. GIN indexes the tsvector. SQLite never populates the column, so
there the index is partial and stays empty.

Revision ID: e7b3c1a9d4f2
Revises: d4a9b7e52c10
Create Date: 2026-10-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7b3c1a9d4f2"
down_revision: Union[str, None] = "d4a9b7e52c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_records_search_vector",
        "records",
        ["search_vector"],
        postgresql_using="gin",
        sqlite_where=sa.text("search_vector IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_records_search_vector", table_name="records")
