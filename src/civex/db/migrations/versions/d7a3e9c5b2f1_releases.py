"""releases: frozen, citable copies of the data

A release names a version, says what it is (title, authors, licence, DOI,
keywords) and keeps the manifest of a small bundle of its records, which lives
in the object store. The files it cites are not copied: a release is a third
kind of owner in `file_references` (beside a record and a workflow run), so
garbage collection, file moves and "used by" treat its files like a record's.

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
        sa.Column("keywords", civex.db.models._JSON, nullable=False),
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
        sa.Column("yanked_at", civex.db.models._UTCDateTime(), nullable=True),
        sa.Column("yanked_by", sa.String(200), nullable=True),
        sa.Column("yanked_reason", sa.Text(), nullable=True),
        sa.Column("indexed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ux_releases_name", "releases", ["name"], unique=True)

    with op.batch_alter_table("file_references") as batch:
        batch.add_column(sa.Column("release_id", sa.Uuid(), nullable=True))
        batch.drop_constraint("ck_file_references_one_owner", type_="check")
        batch.create_check_constraint("ck_file_references_one_owner", _ONE_OWNER)
        batch.create_foreign_key(
            "fk_file_references_release",
            "releases",
            ["release_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_file_refs_release_sha", ["release_id", "sha256"]
        )


_ONE_OWNER = (
    "(CASE WHEN record_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN job_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN release_id IS NULL THEN 0 ELSE 1 END) = 1"
)
_TWO_OWNERS = (
    "(record_id IS NOT NULL AND job_id IS NULL) "
    "OR (record_id IS NULL AND job_id IS NOT NULL)"
)


def downgrade() -> None:
    op.execute("DELETE FROM file_references WHERE release_id IS NOT NULL")
    with op.batch_alter_table("file_references") as batch:
        batch.drop_constraint("uq_file_refs_release_sha", type_="unique")
        batch.drop_constraint("fk_file_references_release", type_="foreignkey")
        batch.drop_constraint("ck_file_references_one_owner", type_="check")
        batch.create_check_constraint("ck_file_references_one_owner", _TWO_OWNERS)
        batch.drop_column("release_id")
    op.drop_index("ux_releases_name", table_name="releases")
    op.drop_table("releases")
