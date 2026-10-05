"""A device and its authority: joining, seeding, syncing, and surviving failures."""

from __future__ import annotations

import pytest

from civex.domain.sync import SyncError

from .peers import connect, device, flaky, snapshots


def build_study(ctx):
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field("encounter", "site", "string")
    ctx.schema_svc.add_field("encounter", "depth", "float")
    ctx.dataset_svc.create("study")
    ctx.dataset_svc.update("study", schemas=["encounter"])
    record = ctx.record_svc.add("study", "encounter", {"site": "x", "depth": 1.0})
    ctx.commit()
    return record


@pytest.fixture()
def authority(project):
    return project("authority")


def data(ctx, record):
    return ctx.record_svc.get(str(record.id)).data


# --- joining ----------------------------------------------------------------


def test_a_project_with_data_fills_an_empty_authority_and_agrees_on_the_project(
    project, authority
):
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    before = laptop.sync_repo.meta().project_id

    assert connect(laptop) == "seeded"

    assert snapshots(authority) == snapshots(laptop)
    assert authority.sync_repo.meta().project_id == laptop.sync_repo.meta().project_id
    assert laptop.sync_repo.meta().project_id != before  # it took the authority's
    assert laptop.sync_repo.meta().cursor == authority.sync_repo.head_seq()
    assert laptop.sync_repo.count_pending() == 0
    assert laptop.sync_svc.sync().changed is False  # already level
    assert data(authority, record)["site"] == "x"


def test_an_empty_project_joins_one_that_has_data_and_keeps_its_history(
    project, authority
):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    connect(laptop)

    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"

    assert snapshots(phone) == snapshots(authority)
    assert phone.sync_repo.meta().project_id == authority.sync_repo.meta().project_id
    history = phone.history_svc.page(limit=500)
    assert len(history) >= 4  # the authority's history, not just its state
    assert phone.sync_repo.count_pending() == 0


def test_two_projects_that_both_hold_data_are_not_merged(project, authority):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    connect(laptop)

    other = device(project, authority, "other")
    other.schema_svc.create("mine_already")
    other.commit()
    with pytest.raises(SyncError, match="both already hold data") as raised:
        connect(other)
    assert raised.value.retryable is False
    assert other.sync_repo.meta().project_id != authority.sync_repo.meta().project_id
    assert other.sync_svc.configured is False


def test_two_empty_projects_just_agree(project, authority):
    laptop = device(project, authority, "laptop")
    assert connect(laptop) == "empty"
    laptop.schema_svc.create("thing")
    laptop.commit()
    assert laptop.sync_svc.sync().pushed == 1
    assert authority.sync_repo.snapshot("schema", laptop.schema_svc.get("thing").id)


def test_connecting_again_carries_on(project, authority):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    connect(laptop)
    assert connect(laptop) == "resumed"


# --- syncing ----------------------------------------------------------------


@pytest.fixture()
def pair(project, authority):
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    return laptop, phone, record


def test_a_change_on_one_device_reaches_the_other(pair, authority):
    laptop, phone, record = pair
    laptop.record_svc.update(str(record.id), {"site": "changed", "depth": 1.0})
    laptop.commit()

    assert laptop.sync_svc.sync().pushed == 1
    assert phone.sync_svc.sync().pulled >= 1

    assert data(phone, record)["site"] == "changed"
    assert snapshots(phone) == snapshots(laptop) == snapshots(authority)


def test_edits_to_different_fields_on_two_devices_both_survive(pair):
    laptop, phone, record = pair
    laptop.record_svc.update(str(record.id), {"site": "L", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "x", "depth": 9.0})
    laptop.commit()
    phone.commit()

    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()

    assert data(laptop, record) == data(phone, record) == {"site": "L", "depth": 9.0}
    assert phone.sync_svc.conflicts() == []


def test_two_edits_to_one_field_keep_the_first_and_keep_the_other_for_review(pair):
    laptop, phone, record = pair
    laptop.record_svc.update(str(record.id), {"site": "laptop", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "phone", "depth": 1.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()

    report = phone.sync_svc.sync()

    assert report.conflicts == 1
    assert data(phone, record)["site"] == "laptop"  # it ends where the authority is
    (conflict,) = phone.sync_svc.conflicts()
    assert (conflict.yours, conflict.theirs) == ("phone", "laptop")
    assert phone.sync_svc.status().open_conflicts == 1

    # "Use mine" is an ordinary edit that then syncs everywhere.
    phone.sync_svc.resolve_conflict(conflict.id, "mine")
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    assert data(phone, record)["site"] == data(laptop, record)["site"] == "phone"
    assert phone.sync_svc.status().open_conflicts == 0


def test_keeping_theirs_just_settles_it(pair):
    laptop, phone, record = pair
    laptop.record_svc.update(str(record.id), {"site": "laptop", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "phone", "depth": 1.0})
    laptop.commit()
    phone.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    (conflict,) = phone.sync_svc.conflicts()
    phone.sync_svc.resolve_conflict(conflict.id, "theirs")
    assert phone.sync_svc.conflicts() == []
    assert data(phone, record)["site"] == "laptop"


def test_a_pull_does_not_overwrite_what_has_not_been_sent(pair):
    laptop, phone, record = pair
    laptop.record_svc.update(str(record.id), {"site": "laptop", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    phone.record_svc.update(str(record.id), {"site": "x", "depth": 5.0})
    phone.commit()

    phone.sync_svc.pull()  # sees the laptop's change, but must not lose its own

    assert data(phone, record)["depth"] == 5.0
    phone.sync_svc.sync()
    assert data(phone, record) == {"site": "laptop", "depth": 5.0}  # both


def test_a_delete_and_its_restore_travel_as_a_group(pair, project):
    laptop, phone, record = pair
    laptop.schema_svc.create("recording", parent="encounter")
    laptop.schema_svc.add_field("recording", "rate", "integer")
    laptop.dataset_svc.update("study", schemas=["encounter", "recording"])
    for rate in (1, 2, 3):
        laptop.record_svc.add(
            "study", "recording", {"rate": rate}, parent_record_id=str(record.id)
        )
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    laptop.record_svc.delete(str(record.id))
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    assert phone.record_svc.labels([str(record.id)])[0].deleted_at is not None
    assert phone.record_svc.find("study", "recording") == []

    phone.record_svc.restore(str(record.id))  # the group, on the other device
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    assert len(laptop.record_svc.find("study", "recording")) == 3


def test_renames_travel_because_things_are_identified_by_id(pair):
    laptop, phone, record = pair
    laptop.schema_svc.update_field("encounter", "site", new_name="place")
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    assert data(phone, record) == {"place": "x", "depth": 1.0}


def test_a_permanent_delete_removes_the_thing_and_its_history_everywhere(pair):
    laptop, phone, record = pair
    laptop.record_svc.delete(str(record.id))
    laptop.record_svc.purge(str(record.id))
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    assert phone.sync_repo.snapshot("record", record.id) is None
    about = [e for e in phone.history_svc.page(limit=500) if e.entity_id == record.id]
    assert [e.action for e in about] == ["purge"]


def test_syncing_again_with_nothing_new_does_nothing(pair):
    laptop, phone, _ = pair
    laptop.sync_svc.sync()
    report = phone.sync_svc.sync()
    assert report.changed is False and report.conflicts == 0


# --- failures ---------------------------------------------------------------


def test_a_lost_reply_is_survived_without_doing_anything_twice(project, authority):
    laptop = device(project, authority, "laptop", flaky=True)
    record = build_study(laptop)
    connect(laptop)
    laptop.record_svc.update(str(record.id), {"site": "once", "depth": 1.0})
    laptop.commit()
    entries_before = len(authority.sync_repo.entries_after(0, 1000)[0])

    flaky(laptop).fail("push", "lose_reply")
    with pytest.raises(SyncError, match="dropped") as raised:
        laptop.sync_svc.sync()
    assert raised.value.retryable is True
    # The authority took it; the device never heard, so it still has it pending.
    assert laptop.sync_repo.count_pending() == 1
    assert laptop.sync_svc.status().last_error

    report = laptop.sync_svc.sync()  # try again

    assert laptop.sync_repo.count_pending() == 0
    assert len(authority.sync_repo.entries_after(0, 1000)[0]) == entries_before + 1
    assert data(authority, record)["site"] == "once"
    assert laptop.sync_svc.status().last_error is None
    assert report.conflicts == 0


def test_a_network_that_is_down_loses_nothing(project, authority):
    laptop = device(project, authority, "laptop", flaky=True)
    record = build_study(laptop)
    connect(laptop)
    laptop.record_svc.update(str(record.id), {"site": "later", "depth": 1.0})
    laptop.commit()

    flaky(laptop).fail("hello", "refuse")
    with pytest.raises(SyncError):
        laptop.sync_svc.sync()
    assert laptop.sync_repo.count_pending() == 1

    laptop.sync_svc.sync()
    assert data(authority, record)["site"] == "later"


def test_a_pull_that_fails_part_way_resumes_where_it_stopped(project, authority):
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone", flaky=True)
    connect(phone)
    for n in range(5):
        laptop.record_svc.update(str(record.id), {"site": f"v{n}", "depth": float(n)})
        laptop.commit()
    laptop.sync_svc.sync()

    flaky(phone).fail("feed", "refuse")
    with pytest.raises(SyncError):
        phone.sync_svc.sync()
    assert phone.sync_svc.sync().pulled >= 5
    assert data(phone, record) == data(laptop, record)


def test_a_refused_token_is_not_something_to_retry(project, authority):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    connect(laptop)
    authority.authority_svc.revoke_device("laptop")
    authority.commit()
    with pytest.raises(SyncError, match="revoked") as raised:
        laptop.sync_svc.sync()
    assert raised.value.retryable is False


def test_a_server_on_another_protocol_is_refused_clearly(
    project, authority, monkeypatch
):
    laptop = device(project, authority, "laptop")
    monkeypatch.setattr("civex.services.sync_service.PROTOCOL_VERSION", 99)
    with pytest.raises(SyncError, match="protocol") as raised:
        connect(laptop)
    assert raised.value.retryable is False


def test_one_sync_at_a_time(pair):
    from civex.services.sync_lock import SyncBusy, sync_lock

    laptop, _, _ = pair
    with sync_lock(laptop.sync_svc._config.civex_dir):
        with pytest.raises(SyncBusy):
            laptop.sync_svc.sync()
    laptop.sync_svc.sync()  # free again


def _record_with_unreadable_file(laptop, record):
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    laptop.sync_svc.sync()
    ref = laptop.file_svc.store_bytes(b"gone for now", "scan.bin")
    path = laptop.file_svc.object_path(ref.sha256)
    saved = path.read_bytes()
    laptop.record_svc.update(
        str(record.id), {"site": "a", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    path.unlink()  # the drive is unplugged
    return ref, path, saved


def test_a_file_the_device_cannot_read_does_not_hold_the_change_back(pair, authority):
    laptop, _, record = pair
    ref, _path, _saved = _record_with_unreadable_file(laptop, record)

    report = laptop.sync_svc.sync()

    assert report.pushed >= 1 and laptop.sync_repo.count_pending() == 0
    assert data(authority, record)["scan"]["sha256"] == ref.sha256
    assert not authority.file_svc.exists(ref.sha256)
    assert report.owed_files == [ref.sha256]


def test_the_owed_file_goes_by_itself_when_it_can_be_read_again(pair, authority):
    laptop, _, record = pair
    ref, path, saved = _record_with_unreadable_file(laptop, record)
    laptop.sync_svc.sync()
    again = laptop.sync_svc.sync()  # still unplugged: nothing to do, nothing breaks
    assert again.owed_files == [ref.sha256]

    path.write_bytes(saved)  # the drive is plugged back in
    report = laptop.sync_svc.sync()

    assert authority.file_svc.exists(ref.sha256)
    assert report.files_sent == 1 and report.owed_files == []


def test_one_lost_file_does_not_hold_up_unrelated_changes(pair, authority):
    laptop, _, record = pair
    _record_with_unreadable_file(laptop, record)
    other = laptop.record_svc.add("study", "encounter", {"site": "b", "depth": 2.0})
    laptop.commit()

    laptop.sync_svc.sync()

    assert data(authority, other) is not None
    status = laptop.sync_svc.status()
    assert status.last_error is None  # owing a file is not a failure


def test_files_a_change_cites_are_sent_first(pair, authority):
    laptop, _, record = pair
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    laptop.sync_svc.sync()
    ref = laptop.file_svc.store_bytes(b"real bytes", "scan.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()

    report = laptop.sync_svc.sync()

    assert report.files_sent == 1 and report.pushed >= 1
    assert authority.file_svc.exists(ref.sha256)
    assert data(authority, record)["scan"]["sha256"] == ref.sha256


# --- identity ---------------------------------------------------------------


def test_once_syncing_every_new_entry_carries_the_device_and_a_rising_clock(
    project, authority, tmp_path
):
    import os

    from civex.config import load_config
    from civex.context import build_local_context

    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    root = laptop.sync_svc._config.project_root
    laptop.close()
    previous = os.getcwd()
    os.chdir(root)
    try:
        reopened = build_local_context(load_config())
    finally:
        os.chdir(previous)
    try:
        for n in range(3):
            reopened.record_svc.update(str(record.id), {"site": f"s{n}", "depth": 1.0})
        reopened.commit()
        pending = reopened.sync_repo.pending_entries(10)
        assert len(pending) == 3
        assert all(e.device_id for e in pending)
        stamps = [e.hlc for e in pending]
        assert all(stamps) and stamps == sorted(stamps) and len(set(stamps)) == 3
    finally:
        reopened.close()
