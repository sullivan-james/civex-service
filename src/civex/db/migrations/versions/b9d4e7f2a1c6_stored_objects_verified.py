"""stored_objects: when a copy's bytes were checked against its hash

A copy civex wrote itself was hashed as it was written, so every existing row
is verified at the moment it was recorded. A file that goes straight into a
bucket in parts (a presigned multipart upload) is recorded unverified and
checked by a read-back later (`ObjectStore.verify`).

Revision ID: b9d4e7f2a1c6
Revises: a7c3e9f1b5d2
Create Date: 2026-10-11 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4e7f2a1c6"
down_revision: Union[str, None] = "a7c3e9f1b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A plain ADD COLUMN: nullable, so no table rebuild on SQLite.
    op.add_column(
        "stored_objects", sa.Column("verified_at", sa.DateTime(), nullable=True)
    )
    op.execute("UPDATE stored_objects SET verified_at = created_at")


def downgrade() -> None:
    op.drop_column("stored_objects", "verified_at")
