"""The services hold whoever is calling to what they may do, at the boundary:
a project built for a person with a role refuses in one place, with the same
words everywhere, and the local user is held to nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from civex.config import FileConfigStore, load_config_at
from civex.context import AppContext, build_context, build_local_context
from civex.domain import permissions as p
from civex.domain.exceptions import NotAllowedError
from civex.domain.permissions import Permissions
from civex.project import Project, scaffold_project


@pytest.fixture()
def study(tmp_path: Path):
    """A project with two collections, set up by its owner; then a context
    on it for a person who may only write records in the first."""
    root = tmp_path / "study"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("sample")
    owner.schema_svc.add_field("sample", "label", "string")
    owner.schema_svc.add_field("sample", "scan", "file")
    mine = owner.dataset_svc.create("mine")
    theirs = owner.dataset_svc.create("theirs")
    kept = owner.record_svc.add("theirs", "sample", {"label": "kept"})
    owner.commit()

    def as_(perms: Permissions) -> AppContext:
        return build_context(
            Project(
                config=load_config_at(root),
                config_store=FileConfigStore(root),
                actor="Dr Example",
                permissions=perms,
            )
        )

    yield owner, as_, mine, theirs, kept
    owner.close()


def test_a_writer_writes_only_where_allowed(study):
    owner, as_, mine, theirs, kept = study
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS, collections=[mine.id]))
    try:
        made = writer.record_svc.add("mine", "sample", {"label": "ok"})
        writer.record_svc.update(str(made.id), {"label": "changed"})
        writer.record_svc.patch(str(made.id), {"label": "patched"})
        with pytest.raises(NotAllowedError, match="You may not add, change"):
            writer.record_svc.add("theirs", "sample", {"label": "no"})
        with pytest.raises(NotAllowedError):
            writer.record_svc.update(str(kept.id), {"label": "no"})
        # Deleting takes a right of its own, even in the writer's collection.
        with pytest.raises(NotAllowedError, match="You may not delete"):
            writer.record_svc.delete(str(made.id))
        with pytest.raises(NotAllowedError):
            writer.record_svc.delete_many([str(made.id), str(kept.id)])
        # Reading is never in question.
        assert writer.record_svc.get(str(kept.id)).data["label"] == "kept"
        # Nor is a saved filter for a writer.
        writer.view_svc.create("sample", "labelled", columns=["label"])
        writer.commit()
    finally:
        writer.close()
    assert owner.record_svc.get(str(kept.id)).data["label"] == "kept"


def test_structure_and_files_take_their_own_rights(study):
    owner, as_, mine, theirs, kept = study
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS))
    try:
        with pytest.raises(NotAllowedError, match="You may not change kinds"):
            writer.schema_svc.add_field("sample", "weight", "float")
        with pytest.raises(NotAllowedError):
            writer.schema_svc.create("other")
        with pytest.raises(NotAllowedError):
            writer.dataset_svc.update("mine", description="x")
        with pytest.raises(NotAllowedError, match="You may not delete"):
            writer.dataset_svc.delete("mine")
        with pytest.raises(NotAllowedError, match="You may not add files"):
            writer.file_svc.store_bytes(b"scan", "scan.bin")
    finally:
        writer.close()
    builder = as_(Permissions.of(p.READ, p.CHANGE_STRUCTURE, p.MANAGE_FILES))
    try:
        builder.schema_svc.add_field("sample", "weight", "float")
        builder.dataset_svc.update("mine", description="x")
        builder.file_svc.store_bytes(b"scan", "scan.bin")
        with pytest.raises(NotAllowedError):
            builder.record_svc.add("mine", "sample", {"label": "no"})
        with pytest.raises(NotAllowedError, match="You may not delete"):
            builder.schema_svc.delete("sample")
        builder.commit()
    finally:
        builder.close()


def test_deleting_and_restoring_are_checked_before_anything_moves(study):
    owner, as_, mine, theirs, kept = study
    one = owner.record_svc.add("mine", "sample", {"label": "one"})
    owner.commit()
    deleter = as_(
        Permissions.of(p.READ, p.WRITE_RECORDS, p.DELETE, collections=[mine.id])
    )
    try:
        # A bulk delete spanning a collection they may not touch does nothing.
        with pytest.raises(NotAllowedError):
            deleter.record_svc.delete_many([str(one.id), str(kept.id)])
        deleter.commit()
        assert owner.record_svc.get(str(one.id)).deleted_at is None
        deleter.record_svc.delete(str(one.id))
        deleter.commit()
    finally:
        deleter.close()
    owner.record_svc.delete(str(kept.id))
    owner.commit()
    reader = as_(Permissions.of(p.READ))
    try:
        with pytest.raises(NotAllowedError):
            reader.record_svc.restore(str(one.id))
        with pytest.raises(NotAllowedError):
            reader.record_svc.restore_records([str(one.id)])
        with pytest.raises(NotAllowedError):
            reader.record_svc.purge(str(one.id))
    finally:
        reader.close()
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS, collections=[mine.id]))
    try:
        assert writer.record_svc.restore(str(one.id)).deleted_at is None
        with pytest.raises(NotAllowedError):  # not theirs to bring back
            writer.record_svc.restore_records([str(kept.id)])
    finally:
        writer.close()
