"""Files records cite that this project never stored and nothing can supply:
listed, ignored (and forgotten when the file turns up), or taken out of the
records as ordinary, undoable, synced edits."""

from __future__ import annotations

import pytest

from civex.testing.peers import build_study, connect, device


@pytest.fixture()
def study(project, authority):
    laptop = device(project, authority, "laptop")
    first = build_study(laptop)
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.schema_svc.add_field("encounter", "extras", "file_list")
    laptop.commit()
    second = laptop.record_svc.add("study", "encounter", {"site": "y", "depth": 2.0})
    laptop.commit()
    connect(laptop)
    return laptop, authority, first, second


def _cite_lost_file(ctx, record, content: bytes, field: str = "scan"):
    """A record citing a file this project never stored."""
    ref = ctx.file_svc.store_bytes(content, "lost.bin")
    value = ref.to_dict() if field == "scan" else [ref.to_dict()]
    ctx.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, field: value}
    )
    ctx.commit()
    ctx.file_svc._store.delete(ref.sha256)
    ctx.commit()
    return ref.sha256


def _data(ctx, record):
    return ctx.record_svc.get(str(record.id)).data


def test_missing_files_are_listed_by_collection_and_field(study):
    laptop, _, first, second = study
    sha = _cite_lost_file(laptop, first, b"one")
    _cite_lost_file(laptop, second, b"two", "extras")
    laptop.sync_svc.sync()
    report = laptop.sync_svc.missing_files()
    assert len(report.shas) == 2 and sha in report.shas
    fields = {(g.collection, g.schema, g.field, g.records) for g in report.groups}
    assert fields == {("study", "encounter", "scan", 1), ("study", "encounter", "extras", 1)}


def test_a_file_that_exists_here_is_never_listed(study):
    laptop, _, first, _ = study
    ref = laptop.file_svc.store_bytes(b"here", "here.bin")
    laptop.record_svc.update(
        str(first.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    assert laptop.sync_svc.missing_files().shas == []
    assert laptop.sync_svc.remove_missing([ref.sha256]).changed == 0
    assert _data(laptop, first)["scan"]["sha256"] == ref.sha256


def test_a_file_the_server_holds_is_never_listed(study):
    laptop, authority, first, _ = study
    sha = _cite_lost_file(laptop, first, b"on the server")
    laptop.sync_svc.sync()
    # The authority has it (stored there), so it is not missing everywhere.
    authority.file_svc.store_bytes(b"on the server", "x.bin")
    assert sha not in laptop.sync_svc.missing_files().shas
    assert laptop.sync_svc.remove_missing([sha]).changed == 0


def test_a_dry_run_changes_nothing(study):
    laptop, _, first, second = study
    sha = _cite_lost_file(laptop, first, b"one")
    _cite_lost_file(laptop, second, b"two")
    laptop.sync_svc.sync()
    pending = laptop.sync_svc.status().pending
    result = laptop.sync_svc.remove_missing(
        laptop.sync_svc.missing_files().shas, dry_run=True
    )
    assert result.changed == 2
    assert _data(laptop, first)["scan"]["sha256"] == sha
    assert laptop.sync_svc.status().pending == pending


def test_removing_edits_the_records_syncs_and_is_undone_as_one_event(study):
    laptop, authority, first, second = study
    _cite_lost_file(laptop, first, b"one")
    _cite_lost_file(laptop, second, b"two", "extras")
    laptop.sync_svc.sync()
    shas = laptop.sync_svc.missing_files().shas

    result = laptop.sync_svc.remove_missing(shas)
    assert result.changed == 2 and result.skipped == []
    assert not _data(laptop, first).get("scan")
    assert not _data(laptop, second).get("extras")
    assert laptop.sync_svc.missing_files().shas == []

    # An ordinary edit: it syncs to the authority.
    laptop.sync_svc.sync()
    assert not authority.record_svc.get(str(first.id)).data.get("scan")

    # One event in Activity, as a bulk edit is. (Undo is refused by the audit
    # rule that a reference to a file with no stored content isn't put back.)
    found, _ = laptop.history_svc.events(
        where={"field": "how", "op": "eq", "value": "edit"}, limit=1
    )
    assert found[0].batch.label == "remove missing files"
    plan = laptop.history_svc.revert_batch(found[0].batch.id)
    assert plan.entries == 2 and plan.applied == 0


def test_a_required_file_field_is_reported_and_left(study):
    laptop, _, first, _ = study
    laptop.schema_svc.create("doc")
    laptop.schema_svc.add_field("doc", "attachment", "file", required=True)
    laptop.commit()
    ref = laptop.file_svc.store_bytes(b"needed", "n.bin")
    record = laptop.record_svc.add("study", "doc", {"attachment": ref.to_dict()})
    laptop.commit()
    laptop.file_svc._store.delete(ref.sha256)
    laptop.commit()

    result = laptop.sync_svc.remove_missing([ref.sha256])
    assert result.changed == 0 and result.skipped_count == 1
    assert "required" in result.skipped[0].reason
    assert _data(laptop, record)["attachment"]["sha256"] == ref.sha256


def test_ignoring_silences_the_warning_and_survives_a_restart(study):
    laptop, _, first, _ = study
    sha = _cite_lost_file(laptop, first, b"one")
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    assert laptop.sync_svc.status().files_waiting.missing == 1

    assert laptop.sync_svc.ignore_missing([sha]) == 1
    status = laptop.sync_svc.status()
    assert status.files_ignored == 1
    assert status.files_waiting is None or status.files_waiting.missing == 0
    report = laptop.sync_svc.missing_files()
    assert report.shas == [] and report.ignored == [sha]
    # The references stay.
    assert _data(laptop, first)["scan"]["sha256"] == sha
    # Kept in the database: a new service over it still knows.
    assert laptop.sync_repo.ignored_missing() == {sha}


def test_a_file_that_turns_up_is_forgotten_and_sent(study):
    laptop, authority, first, _ = study
    sha = _cite_lost_file(laptop, first, b"it comes back")
    laptop.sync_svc.sync()
    laptop.sync_svc.ignore_missing([sha])
    assert laptop.sync_svc.status().files_ignored == 1

    laptop.file_svc.store_bytes(b"it comes back", "back.bin")  # same content: same sha
    laptop.commit()
    report = laptop.sync_svc.send_files()
    assert report.sent == 1
    assert laptop.sync_svc.status().files_ignored == 0
    assert laptop.sync_svc.missing_files().shas == []
