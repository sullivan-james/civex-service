"""library: every version kept, workflows pinned to plugin versions

`library_items` held one row per item, replaced on each publish. It now holds
one row per version (unique on kind, name and version), so a workflow can stay
on the plugin versions it was published with and anything can be rolled back.
A workflow version records those versions (`pins`); a plugin version records
the contract its publisher's computer described (`contract`), so an install can
tell what it would break before running anything. Existing rows become each
item's version as it stands, with no pins and no contract.

Revision ID: e6a2c8f4d1b7
Revises: b2d6f8a3c517
Create Date: 2026-10-08 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "e6a2c8f4d1b7"
down_revision: Union[str, None] = "b2d6f8a3c517"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")
_OLD = "uq_library_items_kind_name"
_NEW = "uq_library_items_kind_name_version"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("library_items")}
    uniques = {u["name"] for u in inspector.get_unique_constraints("library_items")}
    with op.batch_alter_table("library_items") as batch:
        if "pins" not in columns:
            batch.add_column(
                sa.Column("pins", _JSON, nullable=False, server_default=sa.text("'{}'"))
            )
        if "contract" not in columns:
            batch.add_column(sa.Column("contract", _JSON, nullable=True))
        if _OLD in uniques:
            batch.drop_constraint(_OLD, type_="unique")
        if _NEW not in uniques:
            batch.create_unique_constraint(_NEW, ["kind", "name", "version"])


def downgrade() -> None:
    # Only the newest version of each item can stay under the old rule.
    op.execute(
        "DELETE FROM library_items WHERE version < ("
        "SELECT MAX(l.version) FROM library_items l "
        "WHERE l.kind = library_items.kind AND l.name = library_items.name)"
    )
    with op.batch_alter_table("library_items") as batch:
        batch.drop_constraint(_NEW, type_="unique")
        batch.create_unique_constraint(_OLD, ["kind", "name"])
        batch.drop_column("contract")
        batch.drop_column("pins")
