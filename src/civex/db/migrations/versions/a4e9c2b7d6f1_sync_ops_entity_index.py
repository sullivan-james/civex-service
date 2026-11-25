"""sync_ops: an index on the thing a change was to

Revision ID: a4e9c2b7d6f1
Revises: b7d3e9a1c5f8
Create Date: 2026-11-25 12:00:00.000000

The authority says a file cited by a record that arrived lately is `arriving`
(its device is still uploading it), which needs the latest time a change to
each of a page of records was received: the index makes that a lookup, not a
scan of every change ever received.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a4e9c2b7d6f1"
down_revision: Union[str, None] = "b7d3e9a1c5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create(concurrently: bool = False) -> None:
    op.create_index(
        "ix_sync_ops_entity",
        "sync_ops",
        ["entity_id", "received_at"],
        if_not_exists=True,
        postgresql_concurrently=concurrently,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        _create()
        return
    # Built without blocking writes (a big authority keeps taking pushes):
    # CONCURRENTLY cannot run inside a transaction.
    try:
        with op.get_context().autocommit_block():
            _create(concurrently=True)
    except AssertionError:
        # `civex.db.migrate` hands alembic a connection whose transaction it
        # owns, so alembic has none to step out of: commit it (what ran so far
        # is whole, and recorded in the same transaction), build the index
        # outside any transaction, and let the next statement begin another.
        bind.commit()
        previous = bind.get_isolation_level()
        bind.execution_options(isolation_level="AUTOCOMMIT")
        try:
            _create(concurrently=True)
        finally:
            bind.commit()  # ends the no-op transaction the statement began
            bind.execution_options(isolation_level=previous)


def downgrade() -> None:
    op.drop_index("ix_sync_ops_entity", table_name="sync_ops", if_exists=True)
