"""records: the parent/dataset key is checked at commit

A record can be moved to another collection with everything beneath it. The
parent's dataset_id and each child's change in separate statements (sync
applies the move's history entries one record at a time), and after any one of
them a child points at a parent in another collection. The composite foreign
key that ties a child's dataset to its parent's is therefore DEFERRABLE
INITIALLY DEFERRED: still enforced, when the transaction commits.

Revision ID: c4d8e2f6a9b3
Revises: b3c7d1e9f5a2
Create Date: 2026-10-27 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c4d8e2f6a9b3"
down_revision: Union[str, None] = "b3c7d1e9f5a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "fk_records_parent_same_dataset"


def _recreate(deferrable: bool) -> None:
    initially = "DEFERRED" if deferrable else None
    if op.get_bind().dialect.name == "sqlite":
        # SQLite can't alter a constraint: batch mode rebuilds the table.
        with op.batch_alter_table("records", recreate="always") as batch:
            batch.drop_constraint(_FK, type_="foreignkey")
            batch.create_foreign_key(
                _FK,
                "records",
                ["parent_record_id", "dataset_id"],
                ["id", "dataset_id"],
                deferrable=deferrable or None,
                initially=initially,
            )
    else:
        op.drop_constraint(_FK, "records", type_="foreignkey")
        op.create_foreign_key(
            _FK,
            "records",
            "records",
            ["parent_record_id", "dataset_id"],
            ["id", "dataset_id"],
            deferrable=deferrable or None,
            initially=initially,
        )


def upgrade() -> None:
    _recreate(deferrable=True)


def downgrade() -> None:
    _recreate(deferrable=False)
