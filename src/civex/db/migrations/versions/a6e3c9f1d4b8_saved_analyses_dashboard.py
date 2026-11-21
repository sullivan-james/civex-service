"""views.summary and dashboards: saved analyses and the Analytics page

A saved view may carry a summary (its groupings, measures, how it is shown
and where it was made), which makes it a saved analysis. The project's
Analytics page is one row of `dashboards`: the ordered cards on it (saved
analyses and built-in widgets), shared by everyone and synced like a view.

Revision ID: a6e3c9f1d4b8
Revises: bc183bbafef8
Create Date: 2026-11-20 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "a6e3c9f1d4b8"
down_revision: Union[str, None] = "bc183bbafef8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "summary" not in {c["name"] for c in inspector.get_columns("views")}:
        with op.batch_alter_table("views") as batch:
            batch.add_column(sa.Column("summary", civex.db.models._JSON, nullable=True))
    if "dashboards" not in inspector.get_table_names():
        op.create_table(
            "dashboards",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("cards", civex.db.models._JSON, nullable=False),
            sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("dashboards")
    with op.batch_alter_table("views") as batch:
        batch.drop_column("summary")
