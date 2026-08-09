"""schema and field display labels

Splits identity from presentation on both schemas and fields: `name` stays
the machine key (slug-validated from now on, referenced by workflow YAML,
CSV headers and display_fields), and the new nullable `label` carries the
human-facing text -- spaces, capitals, units, whatever reads well.

Nullable with no backfill on purpose: a NULL label means "derive one from
the name", which is what every reader already did implicitly. Existing
non-slug names are left alone -- validation is write-time only, and
`civex schema lint` reports them.

Revision ID: b3d71a04f6c2
Revises: 0291e474801b
Create Date: 2026-08-09 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3d71a04f6c2"
down_revision: Union[str, None] = "0291e474801b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(length=255), nullable=True))
    with op.batch_alter_table("fields", schema=None) as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fields", schema=None) as batch_op:
        batch_op.drop_column("label")
    with op.batch_alter_table("schemas", schema=None) as batch_op:
        batch_op.drop_column("label")
