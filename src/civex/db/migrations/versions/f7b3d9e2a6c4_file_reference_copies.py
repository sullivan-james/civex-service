"""file_references: the copy each record uses

A file may be stored on several drives (`stored_objects` has a row per copy).
Each record's file now points at exactly one of those copies
(`file_references.volume`), so where a record's file is no longer has to be
guessed from whichever copy sorts first.

Existing rows are pointed at a copy here: for each collection, the drive that
holds most of its files, then the next; a file with no copy on this computer
stays NULL until one arrives. Jobs' rows point at any copy.

Revision ID: f7b3d9e2a6c4
Revises: e6a2c8f4d1b7
Create Date: 2026-10-08 00:00:00.000000
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7b3d9e2a6c4"
down_revision: Union[str, None] = "e6a2c8f4d1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHUNK = 500


def upgrade() -> None:
    # A plain ADD COLUMN: a batch rebuild of the table isn't needed for a
    # nullable column, and would rebuild its constraints for nothing.
    op.add_column(
        "file_references", sa.Column("volume", sa.String(length=255), nullable=True)
    )
    op.create_index(
        "ix_file_references_sha_volume", "file_references", ["sha256", "volume"]
    )
    _point_at_copies(op.get_bind())


def _point_at_copies(bind: sa.engine.Connection) -> None:
    copies: dict[str, set[str]] = defaultdict(set)
    for sha, volume in bind.execute(
        sa.text("SELECT sha256, volume FROM stored_objects")
    ):
        copies[sha].add(volume)
    if not copies:
        return
    rows = list(
        bind.execute(
            sa.text(
                "SELECT f.id, f.sha256, r.dataset_id FROM file_references f "
                "LEFT JOIN records r ON r.id = f.record_id"
            )
        )
    )
    # Per collection, its drives by how many of its files each holds.
    held: dict[object, Counter[str]] = defaultdict(Counter)
    for _, sha, dataset in rows:
        for volume in copies.get(sha, ()):
            held[dataset][volume] += 1
    chosen: dict[str, list[object]] = defaultdict(list)
    for ref_id, sha, dataset in rows:
        here = copies.get(sha)
        if not here:
            continue
        ranked = sorted(here, key=lambda v: (-held[dataset][v], v))
        chosen[ranked[0]].append(ref_id)
    for volume, ids in chosen.items():
        for i in range(0, len(ids), _CHUNK):
            bind.execute(
                sa.text(
                    "UPDATE file_references SET volume = :v WHERE id IN :ids"
                ).bindparams(sa.bindparam("ids", expanding=True)),
                {"v": volume, "ids": ids[i : i + _CHUNK]},
            )


def downgrade() -> None:
    op.drop_index("ix_file_references_sha_volume", table_name="file_references")
    with op.batch_alter_table("file_references") as batch:
        batch.drop_column("volume")
