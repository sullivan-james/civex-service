from civex.domain.audit_diff import diff_entry


def _rec(**data):
    return {"id": "r1", "data": data}


def _pairs(changes):
    return {c.field: (c.before, c.after) for c in changes}


def test_record_update_lists_only_changed_fields():
    changes = diff_entry(
        "record", "update", _rec(a=1, b="x", c=3), _rec(a=2, b="x", c=3)
    )
    assert _pairs(changes) == {"a": (1, 2)}


def test_record_create_is_all_new_values():
    changes = diff_entry("record", "create", None, _rec(a=1, b=None, c=""))
    assert _pairs(changes) == {"a": (None, 1)}


def test_record_delete_reports_what_was_lost():
    changes = diff_entry("record", "delete", _rec(a=1, b="x"), None)
    assert _pairs(changes) == {"a": (1, None), "b": ("x", None)}


def test_restore_changes_nothing():
    assert diff_entry("record", "restore", _rec(a=1), _rec(a=1)) == []


def test_derived_file_keys_are_not_an_edit():
    ref = {"sha256": "ab", "filename": "f.txt", "size": 3}
    old = _rec(doc=ref)
    new = _rec(doc={**ref, "resolved_filename": "x.txt", "location": {"volume": "v"}})
    assert diff_entry("record", "update", old, new) == []


def test_blank_to_missing_is_not_a_change():
    assert diff_entry("record", "update", _rec(a=None, t=[]), _rec()) == []


def test_schema_update_diffs_attributes_and_ignores_bookkeeping():
    old = {
        "id": "s",
        "name": "a",
        "label": None,
        "description": "old",
        "created_at": "t",
    }
    new = {
        "id": "s",
        "name": "b",
        "label": None,
        "description": "new",
        "created_at": "t",
    }
    assert _pairs(diff_entry("schema", "update", old, new)) == {
        "description": ("old", "new"),
        "name": ("a", "b"),
    }


def test_field_restrictions_are_real_values():
    old = {"name": "n", "restrictions": {"min": 1}}
    new = {"name": "n", "restrictions": {"min": 1, "max": 5}}
    assert _pairs(diff_entry("field", "update", old, new)) == {
        "restrictions": ({"min": 1}, {"min": 1, "max": 5})
    }


def test_collection_membership_diff():
    old = {"name": "c", "schemas": ["a"]}
    new = {"name": "c", "schemas": ["a", "b"]}
    assert _pairs(diff_entry("dataset", "update", old, new)) == {
        "schemas": (["a"], ["a", "b"])
    }


def test_schema_delete_lists_attributes_going_away():
    changes = diff_entry("schema", "delete", {"id": "s", "name": "a"}, None)
    assert _pairs(changes) == {"name": ("a", None)}
