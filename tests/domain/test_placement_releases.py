"""A release's pointer in a move (`domain.placement.moving`): it never keeps a
copy behind by itself; it goes with the records it shares the copy with once
all of them leave, and stays with them otherwise."""

from __future__ import annotations

import uuid

from civex.domain.placement import Pointer, Scope, keeping, moving

SHA = "a" * 64


def _record(volume: str, collection: str, live: bool = True) -> Pointer:
    return Pointer(uuid.uuid4(), SHA, volume, uuid.uuid4(), collection, live)


def _release(volume: str | None) -> Pointer:
    return Pointer(uuid.uuid4(), SHA, volume, None, None, False, uuid.uuid4())


def test_a_release_follows_when_every_record_at_its_copy_leaves():
    rec, rel = _record("a", "north"), _release("a")
    scope = Scope(collections=frozenset({"north"}))
    assert {p.id for p in moving([rec, rel], scope)} == {rec.id, rel.id}
    assert keeping([rec, rel], scope) == set()


def test_a_release_stays_with_a_record_that_stays():
    north, south, rel = _record("a", "north"), _record("a", "south"), _release("a")
    scope = Scope(collections=frozenset({"north"}))
    assert {p.id for p in moving([north, south, rel], scope)} == {north.id}
    assert keeping([north, south, rel], scope) == {"a"}


def test_a_deleted_record_keeps_its_copy_and_so_the_release_stays():
    live, gone, rel = _record("a", "north"), _record("a", "north", False), _release("a")
    scope = Scope(collections=frozenset({"north"}))
    assert {p.id for p in moving([live, gone, rel], scope)} == {live.id}


def test_a_release_on_another_copy_than_the_records_is_left_alone():
    rec, rel = _record("a", "north"), _release("b")
    scope = Scope(collections=frozenset({"north"}))
    assert [p.id for p in moving([rec, rel], scope)] == [rec.id]
    assert keeping([rec, rel], scope) == {"b"}


def test_emptying_a_drive_takes_every_pointer_at_it():
    rec, rel = _record("a", "north"), _release("a")
    assert len(moving([rec, rel], Scope(drives=frozenset({"a"})))) == 2


def test_gathering_a_release_moves_only_its_pointer():
    rec, rel = _record("a", "north"), _release("a")
    scope = Scope(releases=frozenset({str(rel.release_id)}))
    assert [p.id for p in moving([rec, rel], scope)] == [rel.id]
    assert keeping([rec, rel], scope) == {"a"}
