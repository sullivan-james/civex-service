"""views table

Adds the `views` table: a saved column/filter/sort definition against a
base schema's own fields (see civex.db.models.View). filter_tree reuses the
AND/OR shape from civex.domain.filters unchanged; columns/sort reference
field names rather than ids, the same convention Schema.display_fields uses.

Revision ID: a1c7e5f93b2d
Revises: 6f1a2e9c4d17
Create Date: 2026-08-15 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "a1c7e5f93b2d"
down_revision: Union[str, None] = "6f1a2e9c4d17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("columns", civex.db.models._JSON, nullable=False),
        sa.Column("filter_tree", civex.db.models._JSON, nullable=True),
        sa.Column("sort", civex.db.models._JSON, nullable=False),
        sa.Column(
            "created_at", civex.db.models._UTCDateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(["schema_id"], ["schemas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schema_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("views")
