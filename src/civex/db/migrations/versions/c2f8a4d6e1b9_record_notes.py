"""record_notes: notes on records, in threads

People may leave notes on a record and reply to them (a note with a thread_id
is a reply in that note's thread). Notes sync and are in history.

Revision ID: c2f8a4d6e1b9
Revises: a6e3c9f1d4b8
Create Date: 2026-11-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "c2f8a4d6e1b9"
down_revision: Union[str, None] = "a6e3c9f1d4b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "record_notes" not in inspector.get_table_names():
        op.create_table(
            "record_notes",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "record_id",
                sa.Uuid(),
                sa.ForeignKey("records.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("thread_id", sa.Uuid(), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("author", sa.String(200), nullable=True),
            sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
            sa.Column("edited_at", civex.db.models._UTCDateTime(), nullable=True),
            sa.Column("resolved_at", civex.db.models._UTCDateTime(), nullable=True),
            sa.Column("resolved_by", sa.String(200), nullable=True),
            sa.Column("deleted_at", civex.db.models._UTCDateTime(), nullable=True),
        )
        op.create_index("ix_record_notes_record", "record_notes", ["record_id"])


def downgrade() -> None:
    op.drop_index("ix_record_notes_record", table_name="record_notes")
    op.drop_table("record_notes")
