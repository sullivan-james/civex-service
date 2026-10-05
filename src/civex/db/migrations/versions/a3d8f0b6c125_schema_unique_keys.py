"""schemas.unique_keys: uniqueness policies

A schema can say which field combinations no two of its records may share
(within the same parent record, or the same collection at the top level).
Stored as a JSON list of keys, each a list of the schema's own field ids.

Revision ID: a3d8f0b6c125
Revises: b7f2c9a14d36
Create Date: 2026-10-05 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "a3d8f0b6c125"
down_revision: Union[str, None] = "b7f2c9a14d36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("schemas")}
    if "unique_keys" not in columns:
        with op.batch_alter_table("schemas") as batch:
            batch.add_column(
                sa.Column("unique_keys", civex.db.models._JSON, nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("schemas") as batch:
        batch.drop_column("unique_keys")
