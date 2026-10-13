"""What a caller may do in a project, said once.

A small vocabulary of actions over two kinds of scope: the whole project, or
one collection. A `Permissions` is what the host worked out for whoever is
calling (a person signed in to a hosted civex, a device whose user it knows);
the services ask it at their boundaries (`require`), and the sync authority
asks the very same object about each pushed change (`refuses`, so it is also
a `SyncPolicy`), so a person at a browser and their device are held to one
rule. A project in a folder on this machine has `EVERYTHING`: the local user
may do anything, as they always could. Pure: no imports from the rest of civex
beyond the exceptions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from civex.domain.exceptions import NotAllowedError

READ = "read"
WRITE_RECORDS = "write_records"
CHANGE_STRUCTURE = "change_structure"
MANAGE_FILES = "manage_files"
DELETE = "delete"
MANAGE_MEMBERS = "manage_members"

# Every action, with what it lets a person do, in plain words (the detail of
# the 403 when it is refused, and what the app explains beside a control).
ACTIONS: dict[str, str] = {
    READ: "see the project",
    WRITE_RECORDS: "add, change and restore records, and save filters and exports",
    CHANGE_STRUCTURE: "change kinds of record, their fields and collections",
    MANAGE_FILES: "add files",
    DELETE: "delete records, collections and kinds of record",
    MANAGE_MEMBERS: "decide who may do what",
}

# The scope that covers the whole project, every collection included.
PROJECT = "project"
# `action_for`'s answer for a thing shared by everyone that any writer may
# change (a saved filter): the action in any one collection is enough.
ANYWHERE = object()


def collection_scope(collection_id: Any) -> str:
    return f"collection:{collection_id}"


@dataclass(frozen=True)
class Permissions:
    """`allowed[action]` is where it may be done: `PROJECT`, which covers
    everything, or the collections it is limited to (`collection_scope`). An
    action absent may be done nowhere."""

    allowed: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def everything(cls) -> Permissions:
        return cls({action: frozenset({PROJECT}) for action in ACTIONS})

    @classmethod
    def nothing(cls) -> Permissions:
        return cls({})

    @classmethod
    def of(cls, *actions: str, collections: Iterable[Any] = ()) -> Permissions:
        """These actions everywhere, or, with `collections`, only in those
        (`READ` is always project-wide: a member sees the whole project)."""
        scopes = (
            frozenset(collection_scope(c) for c in collections)
            if collections
            else frozenset({PROJECT})
        )
        return cls(
            {
                action: frozenset({PROJECT}) if action == READ else scopes
                for action in actions
            }
        )

    def can(self, action: str, collection_id: Any = None) -> bool:
        """Whether `action` may be done: anywhere when `collection_id` is None
        (so an action limited to some collections answers False), else in
        that collection."""
        scopes = self.allowed.get(action, frozenset())
        if PROJECT in scopes:
            return True
        return collection_id is not None and collection_scope(collection_id) in scopes

    def can_somewhere(self, action: str) -> bool:
        """Whether `action` may be done in at least one place: what a saved
        filter or export, which is shared by everyone, asks of a writer."""
        return bool(self.allowed.get(action))

    def require(self, action: str, collection_id: Any = None) -> None:
        """Raise `NotAllowedError` (403) unless `can`."""
        if not self.can(action, collection_id):
            raise NotAllowedError(f"You may not {ACTIONS.get(action, action)} here.")

    def require_somewhere(self, action: str) -> None:
        if not self.can_somewhere(action):
            raise NotAllowedError(f"You may not {ACTIONS.get(action, action)} here.")

    # -- as a `SyncPolicy` ---------------------------------------------------

    def refuses(self, who: Any, entry: Any) -> str | None:
        """Why a pushed change may not be made by whoever these permissions
        are for, or None. The same rule the services apply to an edit."""
        action, collection_id = action_for(entry)
        allowed = (
            self.can_somewhere(action)
            if collection_id is ANYWHERE
            else self.can(action, collection_id)
        )
        if allowed:
            return None
        name = (
            getattr(who, "person", None) or getattr(who, "name", None) or "This device"
        )
        return f"{name} may not {ACTIONS.get(action, action)} here."

    # -- as data ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": {
                action: sorted(scopes) for action, scopes in self.allowed.items()
            }
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Permissions:
        return cls(
            {
                str(action): frozenset(str(s) for s in scopes)
                for action, scopes in (d.get("actions") or {}).items()
            }
        )


EVERYTHING = Permissions.everything()


def action_for(entry: Any) -> tuple[str, Any]:
    """Which action a sync entry is, and the collection it is in (None when it
    is about the project's structure): a record made, changed or restored is
    `WRITE_RECORDS` in its collection; a record deleted or purged is `DELETE`
    there; a saved filter is `WRITE_RECORDS` `ANYWHERE`; a collection or kind
    of record deleted or purged is `DELETE`; every other change to a schema,
    field or collection is `CHANGE_STRUCTURE`."""
    kind = getattr(entry, "entity_type", None)
    action = getattr(entry, "action", None)
    removing = action in ("delete", "purge")
    if kind == "record":
        snapshot = (
            getattr(entry, "new_data", None) or getattr(entry, "old_data", None) or {}
        )
        return (DELETE if removing else WRITE_RECORDS), snapshot.get("dataset_id")
    if kind == "view":
        return WRITE_RECORDS, ANYWHERE
    if kind in ("dataset", "schema") and removing:
        return DELETE, None
    return CHANGE_STRUCTURE, None
