"""records: an index on (created_at, id), the order a snapshot is read in

Revision ID: b7c2e5a9d134
Revises: c5e1a8d4b3f7
Create Date: 2026-11-26 18:00:00.000000

A device joining reads the project in pages ordered by `(created_at, id)` with a
keyset cursor. Without an index on that pair every page re-sorts the rows still
to come, so the whole read costs the square of the record count. On a
partitioned `records` PostgreSQL creates it on every partition and merges them.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c2e5a9d134"
down_revision: Union[str, None] = "c5e1a8d4b3f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("records")}
    if "ix_records_created_id" not in indexes:
        op.create_index("ix_records_created_id", "records", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_records_created_id", table_name="records")
