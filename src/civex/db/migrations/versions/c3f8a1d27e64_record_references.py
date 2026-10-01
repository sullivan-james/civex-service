"""record_references: the reverse index of reference/reference_list values

A record's references live only inside its JSON `data`, so "what points at X?"
-- the delete-time referrer check, a record's "Referenced by", the global
collection check, `civex doctor` -- meant searching every record. This table
holds one row per (referring record, field, target record), kept current by
ORM events, so those become indexed lookups. Backfilled here by streaming every
record's `data`.

Revision ID: c3f8a1d27e64
Revises: 9b4d2f6e8a13
Create Date: 2026-10-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Iterable, Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models
from civex.domain.references import collect_record_refs

revision: str = "c3f8a1d27e64"
down_revision: Union[str, None] = "9b4d2f6e8a13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BATCH = 2000
_JSON = civex.db.models._JSON


def _batched(rows: Iterable, n: int = _BATCH):
    batch: list = []
    for row in rows:
        batch.append(row)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


def _backfill() -> None:
    bind = op.get_bind()
    refs = sa.table(
        "record_references",
        sa.column("record_id", sa.Uuid()),
        sa.column("field_id", sa.Uuid()),
        sa.column("target_id", sa.Uuid()),
    )
    records = sa.table("records", sa.column("id", sa.Uuid()), sa.column("data", _JSON))

    def _rows():
        # Per-statement option: Connection.execution_options() mutates `bind`
        # in place, which would make the INSERTs below use a server-side cursor.
        stream = bind.execute(
            sa.select(records.c.id, records.c.data),
            execution_options={"stream_results": True},
        )
        for record_id, data in stream:
            for field_id, target_id in collect_record_refs(data):
                yield {
                    "record_id": record_id,
                    "field_id": field_id,
                    "target_id": target_id,
                }

    for batch in _batched(_rows()):
        bind.execute(sa.insert(refs), batch)


def upgrade() -> None:
    op.create_table(
        "record_references",
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["record_id"], ["records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("record_id", "field_id", "target_id"),
    )
    op.create_index("ix_record_references_target", "record_references", ["target_id"])
    _backfill()


def downgrade() -> None:
    op.drop_index("ix_record_references_target", table_name="record_references")
    op.drop_table("record_references")
