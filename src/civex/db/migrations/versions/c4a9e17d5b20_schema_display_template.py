"""schema display template

A schema's record names were an ordered list of field names joined with a
space. They are now a template (`domain/templating.py`) so a name can carry
literal text and formatted values, e.g. `{site}-{taken_on:YYYY-MM}`.

Each existing list becomes the template that joins the same fields with a
space, so every record keeps its name. Downgrade turns plain `{a} {b}`
templates back into a list; a template with literals or formats can't be
expressed as a list, so only its field names are kept, in order.

Revision ID: c4a9e17d5b20
Revises: c5e1a8d37b42
Create Date: 2026-10-03 16:00:00.000000
"""

from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4a9e17d5b20"
down_revision: Union[str, None] = "c5e1a8d37b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models._JSON -- JSONB on PostgreSQL, plain JSON elsewhere.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_NAME = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)[^{}]*\}")


def upgrade() -> None:
    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("display_template", sa.String(length=1000), nullable=True)
        )

    schemas = sa.table(
        "schemas",
        sa.column("id", sa.Uuid()),
        sa.column("display_fields", _JSON),
        sa.column("display_template", sa.String()),
    )
    bind = op.get_bind()
    for row in bind.execute(sa.select(schemas.c.id, schemas.c.display_fields)):
        names = row.display_fields or []
        if names:
            template = " ".join("{" + n + "}" for n in names)
            bind.execute(
                schemas.update()
                .where(schemas.c.id == row.id)
                .values(display_template=template)
            )

    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.drop_column("display_fields")


def downgrade() -> None:
    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "display_fields", _JSON, nullable=False, server_default=sa.text("'[]'")
            )
        )

    schemas = sa.table(
        "schemas",
        sa.column("id", sa.Uuid()),
        sa.column("display_fields", _JSON),
        sa.column("display_template", sa.String()),
    )
    bind = op.get_bind()
    for row in bind.execute(sa.select(schemas.c.id, schemas.c.display_template)):
        if row.display_template:
            bind.execute(
                schemas.update()
                .where(schemas.c.id == row.id)
                .values(display_fields=_NAME.findall(row.display_template))
            )

    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.drop_column("display_template")
