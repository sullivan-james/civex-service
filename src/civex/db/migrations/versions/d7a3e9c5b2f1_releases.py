"""releases: frozen, citable copies of the data

A release names a version, says what it is (title, authors, licence, DOI) and
keeps the manifest of a bundle made for it, which lives in the object store.

Revision ID: d7a3e9c5b2f1
Revises: c2f8a4d6e1b9
Create Date: 2026-11-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "d7a3e9c5b2f1"
down_revision: Union[str, None] = "c2f8a4d6e1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "releases" in inspector.get_table_names():
        return
    op.create_table(
        "releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("authors", civex.db.models._JSON, nullable=False),
        sa.Column("licence", sa.String(200), nullable=True),
        sa.Column("doi", sa.String(300), nullable=True),
        sa.Column("scope", civex.db.models._JSON, nullable=False),
        sa.Column("include_files", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("bundle_size", sa.BigInteger(), nullable=False),
        sa.Column("counts", civex.db.models._JSON, nullable=False),
        sa.Column("local_seq", sa.BigInteger(), nullable=True),
        sa.Column("feed_seq", sa.BigInteger(), nullable=True),
        sa.Column("civex_version", sa.String(40), nullable=False),
        sa.Column("created_at", civex.db.models._UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.Column("updated_at", civex.db.models._UTCDateTime(), nullable=True),
        sa.Column("withdrawn_at", civex.db.models._UTCDateTime(), nullable=True),
        sa.Column("withdrawn_by", sa.String(200), nullable=True),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
    )
    op.create_index("ux_releases_name", "releases", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_releases_name", table_name="releases")
    op.drop_table("releases")
