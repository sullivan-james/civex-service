"""The rule that settles two edits to one thing."""

from __future__ import annotations

from civex.domain import hlc
from civex.domain.merge import merge


def record(**data):
    return {"id": "r", "schema_id": "s", "created_at": "t", "data": data}


def test_edits_to_different_fields_both_survive():
    base = record(a=1, b=1)
    head = record(a=2, b=1)  # someone changed a
    mine = record(a=1, b=9)  # I changed b
    result = merge(base, head, mine)
    assert result.state["data"] == {"a": 2, "b": 9}
    assert result.conflicts == []
    assert result.changed == ["data.b"]


def test_the_same_edit_twice_is_not_a_conflict():
    base = record(a=1)
    result = merge(base, record(a=5), record(a=5))
    assert result.conflicts == [] and result.changed == []


def test_two_different_edits_to_one_field_keep_head_and_say_so():
    base = record(a=1)
    result = merge(base, record(a=2), record(a=3))
    assert result.state["data"] == {"a": 2}
    (conflict,) = result.conflicts
    assert conflict.field == "data.a"
    assert (conflict.base, conflict.head, conflict.incoming) == (1, 2, 3)
    assert result.changed == []


def test_an_edit_that_changes_nothing_leaves_head_alone():
    base = record(a=1)
    result = merge(base, record(a=2), record(a=1))
    assert result.state["data"] == {"a": 2} and result.conflicts == []


def test_removing_a_value_is_an_edit_too():
    base = record(a=1, b=1)
    result = merge(base, record(a=1, b=1), record(a=1))  # I cleared b
    assert result.state["data"] == {"a": 1}
    assert result.changed == ["data.b"]

    conflict = merge(base, record(a=1, b=2), record(a=1))  # but b was edited
    assert conflict.state["data"] == {"a": 1, "b": 2}
    assert [c.field for c in conflict.conflicts] == ["data.b"]


def test_other_attributes_are_one_value_each():
    base = {"id": "s", "name": "x", "description": "a", "restrictions": {"min": 0}}
    head = {"id": "s", "name": "x", "description": "b", "restrictions": {"min": 0}}
    mine = {"id": "s", "name": "y", "description": "a", "restrictions": {"min": 1}}
    result = merge(base, head, mine)
    assert result.state["name"] == "y"
    assert result.state["restrictions"] == {"min": 1}
    assert result.state["description"] == "b"  # theirs, untouched by me
    assert result.conflicts == []


def test_a_create_that_meets_an_existing_thing_conflicts_where_they_differ():
    head = {"id": "s", "name": "x", "description": "mine?"}
    incoming = {"id": "s", "name": "x", "description": "other"}
    result = merge(None, head, incoming)
    assert [c.field for c in result.conflicts] == ["description"]
    assert result.state["name"] == "x"


def test_lifecycle_keys_are_not_merged_and_names_of_schemas_are_derived():
    base = {"id": "d", "updated_at": "1", "deleted_at": None, "schemas": ["a"]}
    head = {"id": "d", "updated_at": "2", "deleted_at": None, "schemas": ["a"]}
    mine = {"id": "d", "updated_at": "3", "deleted_at": "x", "schemas": ["b"]}
    result = merge(base, head, mine)
    assert result.state == head and result.changed == []


def test_equal_numbers_are_equal_whatever_their_type():
    result = merge(record(a=1), record(a=1.0), record(a=2))
    assert result.state["data"] == {"a": 2}


def test_stamps_sort_as_strings_and_never_go_backwards():
    first = hlc.tick(None, 1_000)
    same_ms = hlc.tick(first, 1_000)
    clock_back = hlc.tick(same_ms, 500)
    later = hlc.tick(clock_back, 2_000)
    assert first < same_ms < clock_back < later
    assert hlc.parse_stamp(later) == (2_000, 0)


def test_after_seeing_a_later_stamp_ours_sorts_after_it():
    seen = hlc.format_stamp(9_000, 3)
    mine = hlc.receive(hlc.tick(None, 1_000), seen, 1_000)
    assert mine > seen
    ahead = hlc.receive(None, hlc.format_stamp(500, 0), 2_000)
    assert hlc.parse_stamp(ahead) == (2_000, 0)
