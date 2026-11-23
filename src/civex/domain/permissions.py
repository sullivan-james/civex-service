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

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from civex.domain.exceptions import NotAllowedError
from civex.domain.file_refs import collect_sha256_refs

READ = "read"
WRITE_RECORDS = "write_records"
CHANGE_STRUCTURE = "change_structure"
ADD_FILES = "add_files"
DELETE_FILES = "delete_files"
# Kept for hosts written before the split: asked or granted, it means both
# `ADD_FILES` and `DELETE_FILES` (see `ALIASES`); it is not an action of its own.
MANAGE_FILES = "manage_files"
DELETE = "delete"
NOTES = "notes"
VIEWS = "views"
MANAGE_MEMBERS = "manage_members"
MANAGE_DEVICES = "manage_devices"
RELEASE = "release"

# Every action, with what it lets a person do, in plain words (the detail of
# the 403 when it is refused, and what the app explains beside a control).
ACTIONS: dict[str, str] = {
    READ: "see the project",
    WRITE_RECORDS: "add, change and restore records, and save filters and exports",
    CHANGE_STRUCTURE: "change kinds of record, their fields and collections",
    ADD_FILES: "add files",
    DELETE_FILES: "delete files from records",
    DELETE: "delete records, collections and kinds of record",
    NOTES: "write, change and delete notes on records",
    VIEWS: "save and change filters, exports and dashboards shared by everyone",
    MANAGE_MEMBERS: "decide who may do what",
    MANAGE_DEVICES: "invite, approve and revoke the devices that sync",
    RELEASE: "make, correct, withdraw and yank releases",
}

# A name that stands for several actions: granting, denying or asking it is
# doing so for each.
ALIASES: dict[str, tuple[str, ...]] = {MANAGE_FILES: (ADD_FILES, DELETE_FILES)}

# An action a host that never heard of it gets wherever another goes: notes
# and shared filters with writing records, releases with changing the
# structure (so a role that could make a release as it was keeps it).
FOLLOWS: dict[str, str] = {
    NOTES: WRITE_RECORDS,
    VIEWS: WRITE_RECORDS,
    RELEASE: CHANGE_STRUCTURE,
}

# What is said when a save cites a file the caller could not download: the
# same words whatever the reason, so the refusal tells nothing about the file.
FILE_UNAVAILABLE = "That file is not available."

# The scope that covers the whole project, every collection included.
PROJECT = "project"
# `action_for`'s answer for a thing shared by everyone that any writer may
# change (a saved filter): the action in any one collection is enough.
ANYWHERE = object()


def collection_scope(collection_id: Any) -> str:
    """The scope naming a collection. Its id is written one way (a pushed
    change may spell it otherwise: upper case, no hyphens), so a rule written
    for the collection cannot be got round by spelling."""
    try:
        return f"collection:{uuid.UUID(str(collection_id))}"
    except ValueError:
        return f"collection:~{collection_id}"


def _spelt(scope: Any) -> str | None:
    """`scope` as `collection_scope` would write it, `PROJECT` as it is, None
    when it is neither."""
    scope = str(scope)
    if scope == PROJECT:
        return PROJECT
    if not scope.startswith("collection:"):
        return None
    rest = scope[len("collection:") :]
    if rest.startswith("~"):
        return scope
    try:
        return f"collection:{uuid.UUID(rest)}"
    except ValueError:
        return None


def _collections(scopes: Iterable[str]) -> frozenset[uuid.UUID]:
    found: set[uuid.UUID] = set()
    for scope in scopes:
        if scope.startswith("collection:"):
            try:
                found.add(uuid.UUID(scope[len("collection:") :]))
            except ValueError:
                continue
    return frozenset(found)


@dataclass(frozen=True)
class ReadScope:
    """The collections whose contents a caller may see. `only` is the whole
    list when they are named, None when they are all but `hidden`. A
    collection made later is seen exactly when the rule says so."""

    only: frozenset[uuid.UUID] | None = None
    hidden: frozenset[uuid.UUID] = frozenset()

    @property
    def unrestricted(self) -> bool:
        return self.only is None and not self.hidden

    def sees(self, collection_id: Any) -> bool:
        if collection_id is None or self.unrestricted:
            return True
        try:
            cid = (
                collection_id
                if isinstance(collection_id, uuid.UUID)
                else uuid.UUID(str(collection_id))
            )
        except ValueError:
            return False
        if self.only is not None:
            return cid in self.only
        return cid not in self.hidden


@dataclass(frozen=True)
class Permissions:
    """`allowed[action]` is where it may be done: `PROJECT`, which covers
    everything, or the collections it is limited to (`collection_scope`). An
    action absent may be done nowhere."""

    allowed: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # `denied[action]` are collections (`collection_scope`) where it may NOT be
    # done even though `allowed` would cover it (`PROJECT` included): a host
    # carving "everything except these" out of a role, so a collection made
    # later is not silently shut out the way listing every allowed one would.
    denied: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # Actions worked out from `WRITE_RECORDS` rather than stated (see
    # `_follow_writing`); kept so a change to writing carries to them.
    derived: frozenset[str] = field(default=frozenset(), compare=False, repr=False)

    def _follow_writing(self) -> None:
        """Notes and shared filters were once part of writing records, and
        releases part of changing the structure. A host that says nothing about
        `NOTES`, `VIEWS` or `RELEASE` (neither granted nor denied, not even to
        nowhere) keeps it so: each goes where the action it came from goes
        (`FOLLOWS`), denials included. Saying anything about one, `lacking`
        included, ends that for it."""
        allowed = dict(self.allowed)
        denied = dict(self.denied)
        derived = set(self.derived)
        for action, parent in FOLLOWS.items():
            if action not in derived and (action in allowed or action in denied):
                continue
            derived.add(action)
            allowed.pop(action, None)
            denied.pop(action, None)
            if parent in allowed:
                allowed[action] = allowed[parent]
            if parent in denied:
                denied[action] = denied[parent]
        object.__setattr__(self, "allowed", allowed)
        object.__setattr__(self, "denied", denied)
        object.__setattr__(self, "derived", frozenset(derived))

    def _spell_aliases(self) -> None:
        """An alias (`MANAGE_FILES`) is spelled out, so the rest of civex only
        ever meets the real actions."""
        for name in ("allowed", "denied"):
            given: Mapping[str, frozenset[str]] = getattr(self, name)
            if not any(a in given for a in ALIASES):
                continue
            spelled: dict[str, frozenset[str]] = {}
            for action, scopes in given.items():
                for real in ALIASES.get(action, (action,)):
                    spelled[real] = spelled.get(real, frozenset()) | frozenset(scopes)
            object.__setattr__(self, name, spelled)

    def _normalise_scopes(self) -> None:
        """Every collection scope in the one spelling `collection_scope` writes
        (a host may send upper case or no hyphens), so the way a rule is spelt
        never decides whether it applies. A grant that cannot be read grants
        nothing; a denial that cannot be read denies the action everywhere: a
        rule is never dropped to let more in."""
        allowed: dict[str, frozenset[str]] = {}
        denied: dict[str, frozenset[str]] = {}
        shut: set[str] = set()
        for action, scopes in self.allowed.items():
            allowed[action] = frozenset(
                n for s in scopes if (n := _spelt(s)) is not None
            )
        for action, scopes in self.denied.items():
            kept: set[str] = set()
            for s in scopes:
                n = _spelt(s)
                if n is None or n == PROJECT:
                    shut.add(action)
                else:
                    kept.add(n)
            if kept:
                denied[action] = frozenset(kept)
        for action in shut:
            allowed[action] = frozenset()
        object.__setattr__(self, "allowed", allowed)
        object.__setattr__(self, "denied", denied)

    def __post_init__(self) -> None:
        # An alias is spelled out first, so a denial of it that cannot be read
        # shuts each real action it stands for, not only itself.
        self._spell_aliases()
        self._normalise_scopes()
        # (continued below: the split of `MANAGE_FILES`, then the actions that
        # follow `WRITE_RECORDS` for a host that has not heard of them)
        self._follow_writing()

    def lacking(self, *actions: str) -> Permissions:
        """These permissions, but `actions` may be done nowhere (stated, so a
        right that would otherwise follow `WRITE_RECORDS` does not)."""
        allowed = dict(self.allowed)
        for action in actions:
            for real in ALIASES.get(action, (action,)):
                allowed[real] = frozenset()
        return Permissions(allowed, self.denied, self.derived - set(actions))

    def without(
        self, actions: Iterable[str], collections: Iterable[Any]
    ) -> Permissions:
        """These permissions, but `actions` may not be done in `collections`."""
        scopes = frozenset(collection_scope(c) for c in collections)
        denied = {a: frozenset(s) for a, s in self.denied.items()}
        for action in actions:
            for real in ALIASES.get(action, (action,)):
                denied[real] = denied.get(real, frozenset()) | scopes
        return Permissions(self.allowed, denied, self.derived - set(actions))

    @classmethod
    def everything(cls) -> Permissions:
        return cls({action: frozenset({PROJECT}) for action in ACTIONS})

    @classmethod
    def nothing(cls) -> Permissions:
        return cls({})

    @classmethod
    def of(
        cls,
        *actions: str,
        collections: Iterable[Any] = (),
        read_collections: Iterable[Any] | None = None,
    ) -> Permissions:
        """These actions everywhere, or, with `collections`, only in those.
        `READ` stays project-wide unless `read_collections` limits it: the
        collections that may be seen (every other is invisible to the caller)."""
        scopes = (
            frozenset(collection_scope(c) for c in collections)
            if collections
            else frozenset({PROJECT})
        )
        read_scopes = (
            frozenset({PROJECT})
            if read_collections is None
            else frozenset(collection_scope(c) for c in read_collections)
        )
        return cls(
            {action: read_scopes if action == READ else scopes for action in actions}
        )

    def can(self, action: str, collection_id: Any = None) -> bool:
        """Whether `action` may be done: anywhere when `collection_id` is None
        (so an action limited to some collections answers False), else in
        that collection."""
        if action in ALIASES:
            return all(self.can(a, collection_id) for a in ALIASES[action])
        if collection_id is not None and collection_scope(
            collection_id
        ) in self.denied.get(action, ()):
            return False
        scopes = self.allowed.get(action, frozenset())
        if PROJECT in scopes:
            return True
        return collection_id is not None and collection_scope(collection_id) in scopes

    def can_somewhere(self, action: str) -> bool:
        """Whether `action` may be done in at least one place: what a saved
        filter or export, which is shared by everyone, asks of a writer."""
        if action in ALIASES:
            return all(self.can_somewhere(a) for a in ALIASES[action])
        return bool(self.allowed.get(action))

    def read_scope(self) -> ReadScope:
        """Which collections the caller can see at all. A collection outside
        it does not exist for them: it is left out of every list, count and
        search, and asking for it directly is a 404, never a 403."""
        scopes = self.allowed.get(READ, frozenset())
        denied = self.denied.get(READ, frozenset())
        hidden = _collections(denied)
        if len(hidden) < len(denied):
            # A denial that names no collection civex can tell is read as
            # denying everything: a rule must never be dropped to let more in.
            return ReadScope(frozenset(), frozenset())
        if PROJECT in scopes:
            return ReadScope(None, hidden)
        return ReadScope(_collections(scopes) - hidden, frozenset())

    def require(self, action: str, collection_id: Any = None) -> None:
        """Raise `NotAllowedError` (403) unless `can`."""
        if not self.can(action, collection_id):
            raise NotAllowedError(f"You may not {ACTIONS.get(action, action)} here.")

    def require_somewhere(self, action: str) -> None:
        if not self.can_somewhere(action):
            raise NotAllowedError(f"You may not {ACTIONS.get(action, action)} here.")

    def require_each(self, action: str, collection_ids: Iterable[Any]) -> None:
        """`require` in every one of these collections, before anything is done."""
        for collection_id in set(collection_ids):
            self.require(action, collection_id)

    # -- as a `SyncPolicy` ---------------------------------------------------

    def refuses(self, who: Any, entry: Any) -> str | None:
        """Why a pushed change may not be made by whoever these permissions
        are for, or None. The same rule the services apply to an edit."""
        action, collection_id = action_for(entry)
        asks: list[tuple[str, Any]] = [(action, collection_id)]
        kind = getattr(entry, "entity_type", None)
        if kind == "record" or (kind == "note" and collection_id is not ANYWHERE):
            # A change to a record in a collection the caller cannot read is
            # refused too, wherever it came from or says it is going.
            asks.append((READ, collection_id))
            before = entry_collections(entry)[0]
            if before is not None and before != collection_id:
                asks.append((READ, before))
        if kind == "dataset" and getattr(entry, "action", None) != "create":
            # Changing or deleting a collection one cannot read: it is not there.
            asks.append((READ, str(getattr(entry, "entity_id", ""))))
        if kind == "record":
            added, removed = file_changes(entry)
            if added:
                asks.append((ADD_FILES, collection_id))
            if removed:
                asks.append((DELETE_FILES, collection_id))
        if kind == "schema" and getattr(entry, "action", None) in (
            "delete",
            "restore",
            "purge",
        ):
            # Removing or bringing back a kind reaches the records of every
            # collection: for someone who can see only some it would skip the
            # rest and tell them they exist, as the data API refuses it.
            if not self.read_scope().unrestricted:
                return "Only someone who can see everything may do that."
        if (
            kind == "schema"
            and getattr(entry, "action", None) == "update"
            and _changes_unique_keys(entry)
            and not self.read_scope().unrestricted
        ):
            # A uniqueness rule is checked against the records of every
            # collection, so what it says of them would reach a caller who
            # cannot see some (the data API refuses it the same way).
            return "Only someone who can see everything may do that."
        for ask, where in asks:
            allowed = (
                self.can_somewhere(ask) if where is ANYWHERE else self.can(ask, where)
            )
            if not allowed:
                name = (
                    getattr(who, "person", None)
                    or getattr(who, "name", None)
                    or "This device"
                )
                return f"{name} may not {ACTIONS.get(ask, ask)} here."
        return None

    # -- as data ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "actions": {
                action: sorted(scopes) for action, scopes in self.allowed.items()
            }
        }
        if self.denied:  # absent when empty, so the common shape is unchanged
            data["denied"] = {
                action: sorted(scopes) for action, scopes in self.denied.items()
            }
        return data

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Permissions:
        return cls(
            {
                str(action): frozenset(str(s) for s in scopes)
                for action, scopes in (d.get("actions") or {}).items()
            },
            {
                str(action): frozenset(str(s) for s in scopes)
                for action, scopes in (d.get("denied") or {}).items()
            },
        )


EVERYTHING = Permissions.everything()


def action_for(entry: Any) -> tuple[str, Any]:
    """Which action a sync entry is, and the collection it is in (None when it
    is about the project's structure): a record made, changed or restored is
    `WRITE_RECORDS` in its collection; a record deleted or purged is `DELETE`
    there; a saved filter or the Analytics page is `VIEWS` `ANYWHERE`, and a note is
    `NOTES` there (its collection is asked about once its record is found); a collection or kind
    of record deleted or purged is `DELETE`; every other change to a schema,
    field or collection is `CHANGE_STRUCTURE`."""
    kind = getattr(entry, "entity_type", None)
    action = getattr(entry, "action", None)
    removing = action in ("delete", "purge")
    if kind == "record":
        return (DELETE if removing else WRITE_RECORDS), entry_collections(entry)[1]
    if kind in ("view", "dashboard"):
        return VIEWS, ANYWHERE
    if kind == "note":
        # A note names its record, not the collection: the authority asks
        # about that collection once it has looked the record up
        # (`SyncAuthorityService._check_note`), naming it in `dataset_id`.
        snapshot = (
            getattr(entry, "new_data", None) or getattr(entry, "old_data", None) or {}
        )
        return NOTES, snapshot.get("dataset_id") or ANYWHERE
    if kind in ("dataset", "schema") and removing:
        return DELETE, None
    return CHANGE_STRUCTURE, None


def entry_collections(entry: Any) -> tuple[Any, Any]:
    """The collection a record change started in and the one it ends in, as
    the authority will store it: a change that travels as what changed
    (`delta`) names where it goes in `delta["dataset_id"]`, not in the
    identity it carries."""
    new = getattr(entry, "new_data", None) or {}
    old = getattr(entry, "old_data", None) or {}
    after = new.get("dataset_id") or old.get("dataset_id")
    before = after
    delta = getattr(entry, "delta", None) or {}
    moved = delta.get("dataset_id")
    if isinstance(moved, Mapping):
        before = moved.get("before") or after
        after = moved.get("after") or after
    elif old.get("dataset_id") and new.get("dataset_id"):
        before, after = old["dataset_id"], new["dataset_id"]
    return before, after


def _changes_unique_keys(entry: Any) -> bool:
    delta = getattr(entry, "delta", None) or {}
    if any(str(path).split(".", 1)[0] == "unique_keys" for path in delta):
        return True
    new = getattr(entry, "new_data", None) or {}
    old = getattr(entry, "old_data", None) or {}
    return "unique_keys" in new and new.get("unique_keys") != old.get("unique_keys")


def file_changes(entry: Any) -> tuple[set[str], set[str]]:
    """The files a record entry cites that its record did not hold, and the
    ones it lets go of (digests): what `ADD_FILES` and `DELETE_FILES` are
    asked about. A delete or purge is judged as a delete, not as files let go."""
    if getattr(entry, "action", None) in ("delete", "purge"):
        return set(), set()
    delta = getattr(entry, "delta", None)
    if delta:
        before: set[str] = set()
        after: set[str] = set()
        for path, change in delta.items():
            if str(path) != "data" and not str(path).startswith("data."):
                continue
            if not isinstance(change, Mapping):
                continue
            before |= collect_sha256_refs(change.get("before"))
            after |= collect_sha256_refs(change.get("after"))
        return after - before, before - after
    new = getattr(entry, "new_data", None) or {}
    after = collect_sha256_refs(new.get("data"))
    if getattr(entry, "action", None) == "create":
        # A thing made holds nothing before, whatever the sender says.
        return after, set()
    old = getattr(entry, "old_data", None) or {}
    before = collect_sha256_refs(old.get("data"))
    return after - before, before - after
