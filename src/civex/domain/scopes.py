"""Collection scope: who may reference the records in a collection.

- ``local``  -- only records in the same collection (the default).
- ``global`` -- records in any collection. Use it for shared reference data
  (species, sites, people) that studies point at.

A reference from a record is valid when its target is in the record's own
collection or in a global one; two local collections never reference each
other. No imports from the rest of civex, like the rest of ``domain``.
"""

from __future__ import annotations

from civex.domain.exceptions import ValidationError

LOCAL = "local"
GLOBAL = "global"
SCOPES = (LOCAL, GLOBAL)


def validate_scope(scope: str) -> str:
    if scope not in SCOPES:
        raise ValidationError(
            f"Invalid scope '{scope}' (must be one of: {', '.join(SCOPES)})"
        )
    return scope


def can_reference(
    source_dataset_id: object, target_dataset_id: object, target_scope: str
) -> bool:
    """Whether a record in `source_dataset_id` may reference a record that
    lives in `target_dataset_id` (whose scope is `target_scope`)."""
    return source_dataset_id == target_dataset_id or target_scope == GLOBAL
