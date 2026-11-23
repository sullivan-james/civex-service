"""A scope is the same rule however it is spelt, and one that cannot be read
never lets more in (review of C3a, item 11)."""

from __future__ import annotations

import uuid

import pytest

from civex.domain import permissions as p
from civex.domain.permissions import Permissions

ID = uuid.UUID("0123456789abcdef0123456789abcdef")
OTHER = uuid.uuid4()


@pytest.mark.parametrize(
    "spelling",
    [
        f"collection:{str(ID).upper()}",
        f"collection:{ID.hex}",
        f"collection:{ID.hex.upper()}",
        f"collection:{{{ID}}}",
    ],
)
def test_a_read_denial_hides_the_collection_however_it_is_spelt(spelling: str):
    perms = Permissions.from_dict(
        {"actions": {p.READ: ["project"]}, "denied": {p.READ: [spelling]}}
    )
    assert not perms.can(p.READ, ID)
    assert perms.can(p.READ, OTHER)
    assert perms.read_scope().hidden == frozenset({ID})
    assert not perms.read_scope().sees(ID)


def test_a_write_denial_in_hex_is_not_ignored():
    perms = Permissions.from_dict(
        {
            "actions": {p.WRITE_RECORDS: ["project"], p.READ: ["project"]},
            "denied": {p.WRITE_RECORDS: [f"collection:{ID.hex.upper()}"]},
        }
    )
    assert not perms.can(p.WRITE_RECORDS, ID)
    assert perms.can(p.WRITE_RECORDS, OTHER)


def test_a_grant_in_hex_covers_the_collection():
    perms = Permissions.from_dict(
        {"actions": {p.READ: [f"collection:{ID.hex.upper()}"]}}
    )
    assert perms.can(p.READ, ID)
    assert not perms.can(p.READ, OTHER)
    assert perms.read_scope().only == frozenset({ID})


@pytest.mark.parametrize("bad", ["collection:not-an-id", "garbage", "collection:", ""])
def test_a_denial_that_cannot_be_read_denies_the_action_everywhere(bad: str):
    perms = Permissions.from_dict(
        {
            "actions": {p.READ: ["project"], p.WRITE_RECORDS: ["project"]},
            "denied": {p.WRITE_RECORDS: [bad]},
        }
    )
    assert not perms.can(p.WRITE_RECORDS, ID)
    assert not perms.can(p.WRITE_RECORDS)
    assert perms.can(p.READ, ID)


def test_a_read_denial_that_cannot_be_read_hides_everything():
    perms = Permissions.from_dict(
        {"actions": {p.READ: ["project"]}, "denied": {p.READ: ["collection:oops"]}}
    )
    assert perms.read_scope().only == frozenset()
    assert not perms.can(p.READ, ID)


def test_a_grant_that_cannot_be_read_grants_nothing():
    perms = Permissions.from_dict(
        {"actions": {p.READ: ["collection:oops", "nonsense"]}}
    )
    assert not perms.can_somewhere(p.READ) or perms.read_scope().only == frozenset()
    assert not perms.can(p.READ, ID)


def test_spelling_is_settled_once_and_round_trips():
    perms = Permissions.from_dict(
        {"actions": {p.READ: [f"collection:{ID.hex.upper()}"]}}
    )
    assert Permissions.from_dict(perms.to_dict()) == perms
    assert perms.to_dict()["actions"][p.READ] == [f"collection:{ID}"]


def test_a_denial_of_an_alias_that_cannot_be_read_shuts_what_it_stands_for():
    perms = Permissions(
        {
            p.ADD_FILES: frozenset({p.PROJECT}),
            p.DELETE_FILES: frozenset({p.PROJECT}),
            p.READ: frozenset({p.PROJECT}),
        },
        {p.MANAGE_FILES: frozenset({"collection:oops"})},
    )
    assert not perms.can(p.ADD_FILES, ID)
    assert not perms.can(p.DELETE_FILES, ID)
    assert not perms.can(p.MANAGE_FILES)
    assert perms.can(p.READ, ID)


def test_a_pushed_uniqueness_rule_is_for_someone_who_sees_everything():
    from types import SimpleNamespace

    def update(**fields):
        return SimpleNamespace(
            entity_type="schema",
            action="update",
            entity_id=uuid.uuid4(),
            old_data={"unique_keys": []},
            new_data=fields,
            delta=None,
        )

    restricted = Permissions.of(
        p.READ, p.CHANGE_STRUCTURE, read_collections=[OTHER]
    )
    whole = Permissions.everything()
    rule = update(unique_keys=[["a"]])
    assert restricted.refuses(None, rule)
    assert whole.refuses(None, rule) is None
    # a schema edit that leaves the rules alone is the caller's to make
    assert restricted.refuses(None, update(label="x")) is None
