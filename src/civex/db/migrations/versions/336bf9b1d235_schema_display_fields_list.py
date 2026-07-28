"""schema display fields list

CIVEX-172: schemas.display_field was a single freeform string naming one field,
with no referential integrity -- renaming or deleting that field left it
dangling silently. Scope was expanded during review to also support a
*combination* of fields for the natural name, so the single string column is
replaced with display_fields, an ordered JSON list of field names. Referential
integrity itself is enforced at the application layer (SchemaService), same as
the single-field version would have been: SQLite has no FK enforcement pragma
enabled anywhere in this codebase, so a real FK/cascade would need app-level
logic regardless.

Existing single-value data is carried forward as a one-element list.

Revision ID: 336bf9b1d235
Revises: c6e4c3b2bbe8
Create Date: 2026-07-28 20:34:24.472398
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "336bf9b1d235"
down_revision: Union[str, None] = "c6e4c3b2bbe8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models._JSON -- JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "display_fields", _JSON, nullable=False, server_default=sa.text("'[]'")
            )
        )

    if bind.dialect.name == "postgresql":
        op.execute(
            "UPDATE schemas SET display_fields = jsonb_build_array(display_field) "
            "WHERE display_field IS NOT NULL"
        )
    else:
        op.execute(
            "UPDATE schemas SET display_fields = json_array(display_field) "
            "WHERE display_field IS NOT NULL"
        )

    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.drop_column("display_field")


def downgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("display_field", sa.String(length=255), nullable=True)
        )

    if bind.dialect.name == "postgresql":
        op.execute(
            "UPDATE schemas SET display_field = display_fields ->> 0 "
            "WHERE jsonb_array_length(display_fields) > 0"
        )
    else:
        op.execute(
            "UPDATE schemas SET display_field = json_extract(display_fields, '$[0]') "
            "WHERE json_array_length(display_fields) > 0"
        )

    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.drop_column("display_fields")
