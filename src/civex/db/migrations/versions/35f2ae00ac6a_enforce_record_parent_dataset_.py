"""enforce record parent dataset consistency

A child record's dataset_id must equal its parent's -- parent_record_id ->
dataset_id is a functional dependency that was previously enforced only in
RecordService.add(), leaving direct repository writes and dump/restore free
to create cross-dataset parent links (CIVEX-168). This pushes the invariant
into the schema: a UNIQUE(id, dataset_id) on records, referenced by a
composite FK on (parent_record_id, dataset_id), makes it impossible for a
child row to point at a parent in a different dataset.

Before applying the constraint, any pre-existing violations are reported and
repaired by clearing parent_record_id on the offending rows -- otherwise the
ADD CONSTRAINT would fail with an opaque integrity error on whichever row it
happens to hit first.

Revision ID: 35f2ae00ac6a
Revises: f70228df9305
Create Date: 2026-07-27 23:31:07.366233
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "35f2ae00ac6a"
down_revision: Union[str, None] = "f70228df9305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# SQLite never records a name for a reflected FK (PRAGMA foreign_key_list
# has no name column), so batch mode can't address the original unnamed
# single-column FK by its real name. This convention gives it a deterministic
# synthetic name purely so drop_constraint() below has something to match.
_SQLITE_FK_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}


def _repair_cross_dataset_parents(bind: sa.engine.Connection) -> None:
    """Find records whose dataset_id disagrees with their parent's, report
    them, and clear parent_record_id so the new FK can be added cleanly."""
    records = sa.table(
        "records",
        sa.column("id", sa.Uuid()),
        sa.column("dataset_id", sa.Uuid()),
        sa.column("parent_record_id", sa.Uuid()),
    )
    child = records.alias("child")
    parent = records.alias("parent")
    violations = bind.execute(
        sa.select(
            child.c.id,
            child.c.dataset_id,
            parent.c.dataset_id.label("parent_dataset_id"),
        )
        .select_from(child.join(parent, child.c.parent_record_id == parent.c.id))
        .where(child.c.dataset_id != parent.c.dataset_id)
    ).fetchall()

    if not violations:
        return

    print(
        f"CIVEX-168: found {len(violations)} record(s) whose dataset_id doesn't "
        "match their parent's. Clearing parent_record_id on these rows so the "
        "new composite foreign key can be applied:"
    )
    for row in violations:
        print(
            f"  record {row.id} (dataset {row.dataset_id}) had parent in "
            f"dataset {row.parent_dataset_id} -- parent link cleared"
        )

    bind.execute(
        records.update()
        .where(records.c.id.in_([row.id for row in violations]))
        .values(parent_record_id=None)
    )


def upgrade() -> None:
    bind = op.get_bind()
    _repair_cross_dataset_parents(bind)

    old_fk_name = next(
        (
            fk["name"]
            for fk in inspect(bind).get_foreign_keys("records")
            if fk["constrained_columns"] == ["parent_record_id"]
        ),
        None,
    )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "records", schema=None, naming_convention=_SQLITE_FK_CONVENTION
        ) as batch_op:
            batch_op.create_unique_constraint(
                "uq_records_id_dataset", ["id", "dataset_id"]
            )
            batch_op.drop_constraint(
                old_fk_name or "fk_records_parent_record_id_records",
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                "fk_records_parent_same_dataset",
                "records",
                ["parent_record_id", "dataset_id"],
                ["id", "dataset_id"],
            )
    else:
        op.create_unique_constraint(
            "uq_records_id_dataset", "records", ["id", "dataset_id"]
        )
        if old_fk_name:
            op.drop_constraint(old_fk_name, "records", type_="foreignkey")
        op.create_foreign_key(
            "fk_records_parent_same_dataset",
            "records",
            "records",
            ["parent_record_id", "dataset_id"],
            ["id", "dataset_id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("records", schema=None) as batch_op:
            batch_op.drop_constraint(
                "fk_records_parent_same_dataset", type_="foreignkey"
            )
            batch_op.create_foreign_key(
                "fk_records_parent_record_id_records",
                "records",
                ["parent_record_id"],
                ["id"],
            )
            batch_op.drop_constraint("uq_records_id_dataset", type_="unique")
    else:
        op.drop_constraint(
            "fk_records_parent_same_dataset", "records", type_="foreignkey"
        )
        op.create_foreign_key(
            "fk_records_parent_record_id_records",
            "records",
            "records",
            ["parent_record_id"],
            ["id"],
        )
        op.drop_constraint("uq_records_id_dataset", "records", type_="unique")
