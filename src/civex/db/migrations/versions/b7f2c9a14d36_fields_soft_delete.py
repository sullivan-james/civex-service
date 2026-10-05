"""fields.deleted_at: deleting a field can be undone

A deleted field used to be removed outright, so its name and settings were gone
and, once a record was next saved, the values it held went with it. A field is
now marked deleted instead (like a schema), the values stay in each record's
data under the field's id, and restoring the field brings them back.

A field's name was unique per schema. That would stop a new field taking the
name of a deleted one, so the rule becomes a unique index over the live fields
only.

Revision ID: b7f2c9a14d36
Revises: a9d3e5f1c708
Create Date: 2026-10-05 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "b7f2c9a14d36"
down_revision: Union[str, None] = "a9d3e5f1c708"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "ux_fields_schema_name_live"
# Names an unnamed UNIQUE gets while SQLite's table is rebuilt, so it can be dropped.
_NAMING = {"uq": "uq_%(table_name)s_%(column_0_N_name)s"}


def _name_unique(inspector) -> str | None:
    """The unique constraint over (schema_id, name), if there is one: its name
    (None when the database doesn't name it, as SQLite) or False for none."""
    for uc in inspector.get_unique_constraints("fields"):
        if list(uc["column_names"]) == ["schema_id", "name"]:
            return uc["name"] or "uq_fields_schema_id_name"
    return None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("fields")}
    unique = _name_unique(inspector)
    indexes = {i["name"] for i in inspector.get_indexes("fields")}

    with op.batch_alter_table("fields", naming_convention=_NAMING) as batch:
        if "deleted_at" not in columns:
            batch.add_column(
                sa.Column("deleted_at", civex.db.models._UTCDateTime(), nullable=True)
            )
        if unique:
            batch.drop_constraint(unique, type_="unique")

    if _INDEX not in indexes:
        op.create_index(
            _INDEX,
            "fields",
            ["schema_id", "name"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    # A deleted field can't be kept: it may share a name with a live one.
    op.execute(sa.text("DELETE FROM fields WHERE deleted_at IS NOT NULL"))
    op.drop_index(_INDEX, table_name="fields")
    with op.batch_alter_table("fields") as batch:
        batch.drop_column("deleted_at")
        batch.create_unique_constraint(
            "uq_fields_schema_id_name", ["schema_id", "name"]
        )
