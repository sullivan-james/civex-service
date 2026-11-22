"""PostgreSQL: partition `records` by hash of id and `audit_log` by month

For repositories that grow to hundreds of millions of rows: a partition is the
unit that vacuum, index rebuilds and bulk loads work on, so a billion-row
repository is maintained one slice at a time. Reads are index-bounded either
way (see docs/contributing/billion-row-collections.md). SQLite is untouched.

- `records`: HASH (id), `PartitionLayout.records_partitions` partitions
  (default 8; `CIVEX_RECORDS_PARTITIONS=off` keeps a plain table). All indexes
  and the foreign keys onto `records.id` are kept.
- `audit_log`: RANGE ("timestamp"), a partition per month plus a default one;
  primary key (id, timestamp); `hub_seq` was never unique in the database.

The existing table is copied into the new layout inside this migration's
transaction (atomic: a failure leaves the old table as it was). Writers wait
for the whole copy and index build; readers only for the final swap. A new or
empty database converts in milliseconds. The copy is not chunked into separate
commits on purpose: the swap needs every row, and a half-copied table could not
be told from a finished one. `civexhub migrate-repos` (or any process opening
the database) runs this per schema.

Downgrade restores plain tables the same way.

Revision ID: b5d8f1a3c6e2
Revises: e4b9c1a7d2f6
Create Date: 2026-11-22 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from civex.db import partitioning

revision: str = "b5d8f1a3c6e2"
down_revision: Union[str, None] = "e4b9c1a7d2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _layout() -> partitioning.PartitionLayout:
    config = op.get_context().config
    given = config.attributes.get("layout") if config is not None else None
    return given or partitioning.PartitionLayout.from_env()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    layout = _layout()
    if layout.audit_monthly:
        partitioning.partition_audit_log(bind, layout.audit_months_ahead)
    partitioning.partition_records(bind, layout.records_partitions)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    partitioning.unpartition_records(bind)
    partitioning.unpartition_audit_log(bind)
