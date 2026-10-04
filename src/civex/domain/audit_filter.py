"""What a history query can ask for, as one value.

Every place that reads history (a record's page, a collection's, the whole
project's, the CLI) is the same query with a different starting point, so the
filters are one object, like `RecordQuery` is for records: the fixed scopes a
caller starts from, a text search, and `where`, the filter tree a person
builds (see `audit_filters`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from civex.domain.filters import FilterNode


@dataclass(frozen=True)
class AuditFilter:
    entity_id: uuid.UUID | None = None  # one thing's history
    entity_ids: list[uuid.UUID] | None = None  # these things'
    entity_type: str | None = None  # record | schema | field | dataset | view
    batch_id: uuid.UUID | None = None  # what is in this batch
    commit_id: uuid.UUID | None = None
    action: str | None = None  # create | update | delete | restore | purge
    since: datetime | None = None
    search: str | None = None  # text in a stored value, a file name, a batch label
    where: FilterNode | None = None  # the filter a person built
