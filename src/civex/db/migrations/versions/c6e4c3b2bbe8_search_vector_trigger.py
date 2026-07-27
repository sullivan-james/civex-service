"""search vector trigger

records.search_vector (CIVEX-173) was only kept in sync by application code
in LocalRecordRepository.create/update -- any write that bypassed that repo
(bulk import, a future sync path, a raw session write) left it stale with no
error. This moves the guarantee into the database: a BEFORE INSERT/UPDATE
trigger recomputes search_vector from `data` on every write, regardless of
which code path performed it.

Mirrors _search_text() in record_repo.py: concatenate the top-level scalar
(string/number) values of `data`, skipping booleans, objects (file refs) and
arrays (file lists). `#>> '{}'` unwraps a jsonb scalar to its text form the
same way Python's str() does for str/int/float.

Postgres-only, matching the column itself: SQLite stores search_vector as
inert text and never queries it (see models._TSVECTOR).

Revision ID: c6e4c3b2bbe8
Revises: f70228df9305
Create Date: 2026-07-27 23:23:06.705523
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c6e4c3b2bbe8"
down_revision: Union[str, None] = "f70228df9305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE FUNCTION records_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('simple', (
                SELECT coalesce(string_agg(entry.value #>> '{}', ' '), '')
                FROM jsonb_each(NEW.data) AS entry
                WHERE jsonb_typeof(entry.value) IN ('string', 'number')
            ));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER records_search_vector_trigger
        BEFORE INSERT OR UPDATE OF data ON records
        FOR EACH ROW EXECUTE FUNCTION records_search_vector_update();
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS records_search_vector_trigger ON records")
    op.execute("DROP FUNCTION IF EXISTS records_search_vector_update()")
