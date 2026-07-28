"""merge heads

Revision ID: 11204ab5d093
Revises: 35f2ae00ac6a, c6e4c3b2bbe8
Create Date: 2026-07-28 21:57:05.371179
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "11204ab5d093"
down_revision: Union[str, Sequence[str], None] = ("35f2ae00ac6a", "c6e4c3b2bbe8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
