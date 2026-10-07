"""Queries over the inventory (`stored_objects`) that the repositories share.

The inventory has a row per copy (a file may be on several drives). A query
asking whether a file is *here*, or how big it is, wants one row per file,
not one per copy, so it joins `stored_files()`, never the table itself."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from civex.db.models import StoredObject


def stored_files() -> Any:
    """One row per file stored on some drive here: `sha`, `size`."""
    return (
        select(
            StoredObject.sha256.label("sha"),
            func.max(StoredObject.size).label("size"),
        )
        .group_by(StoredObject.sha256)
        .subquery("stored_files")
    )
