"""records: a lone file in a file_list field becomes a list of one

A `file_list` value is a list of file references, but until the record
service refused any other shape, a single reference could be stored in one
(`civex.match_files_to_records` wrote the file it matched as it was, whatever
the field's type), and the record page failed on it. Each such value is
wrapped in a list; nothing else is changed. Deleted fields are included, so a
restored field reads right. History is left as it was written.

Revision ID: bc183bbafef8
Revises: c4d8e2f6a9b3
Create Date: 2026-11-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "bc183bbafef8"
down_revision: Union[str, None] = "c4d8e2f6a9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models._JSON -- JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    fields = sa.table("fields", sa.column("id", sa.Uuid()), sa.column("dtype"))
    records = sa.table("records", sa.column("id", sa.Uuid()), sa.column("data", _JSON))
    list_fields = [
        str(row.id)
        for row in bind.execute(
            sa.select(fields.c.id).where(fields.c.dtype == "file_list")
        )
    ]
    for field_id in list_fields:
        # Only records naming the field can hold a value for it; the text test
        # narrows the scan, the shape test below decides.
        named = sa.cast(records.c.data, sa.Text).like(f"%{field_id}%")
        rows = bind.execute(sa.select(records.c.id, records.c.data).where(named))
        for row in rows.fetchall():
            data = row.data or {}
            value = data.get(field_id)
            if isinstance(value, dict):
                bind.execute(
                    records.update()
                    .where(records.c.id == row.id)
                    .values(data={**data, field_id: [value]})
                )


def downgrade() -> None:
    # Lists of one are what the field should always have held: nothing to undo.
    pass
