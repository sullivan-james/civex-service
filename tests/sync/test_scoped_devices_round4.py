"""Round-4 regressions: notes written after the upgrade are not placed by what a
device claimed before it, a device that lags behind the upgrade is still told a
record is gone, history is read again after a grant, and a limited caller's page
size is honoured."""

from __future__ import annotations

import uuid

import pytest

from civex.domain.sync import SyncEntry
from civex.services import sync_authority, sync_service
from civex.testing import connect, device
from civex.testing.peers import read_earlier

from .test_scoped_devices import (  # noqa: F401
    SECRET,
    Study,
    held,
    reads,
    scoped,
    study,
    text_of,
)


def _watermark(authority) -> None:
    repo = authority.sync_repo
    repo.sequence_local_entries()
    repo._meta_row().placed_from = repo.head_seq()
    authority.commit()


def _history(ctx) -> str:
    return str([e.to_dict() for e in ctx.sync_repo.entries_after(0, 5000)[0]])


def _claim(study: Study, seen, marker: str) -> None:
    """What an older civex stored for a stale push: it says `open`."""
    authority = study.authority
    base = authority.authority_svc._applier.head("record", seen.id)
    key = next(k for k, v in base["data"].items() if isinstance(v, str))
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="update",
        entity_type="record",
        entity_id=seen.id,
        old_data={"id": str(seen.id), "dataset_id": str(study.open.id)},
        new_data={"id": str(seen.id), "dataset_id": str(study.open.id)},
        delta={f"data.{key}": {"before": base["data"][key], "after": marker}},
        timestamp="2026-01-02T00:00:00+00:00",
    )
    repo = authority.sync_repo
    repo.insert_entry(entry, hub_seq=repo.next_hub_seq())
    authority.commit()


def _feed_text(study: Study, after: int = 0) -> str:
    page = study.only_open.authority_svc.feed(after, 1000)
    return str([e.to_dict() for e in page.entries])


def test_a_note_written_after_the_upgrade_is_not_placed_by_a_claimed_trail(
    study: Study,
):
    authority = study.authority
    seen = study.open_records[0]
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    study.sync(study.limited)
    _claim(study, seen, "harmless-delta")
    _watermark(authority)
    authority.note_svc.add(str(seen.id), f"{SECRET} NEWNOTE")
    authority.commit()
    assert "NEWNOTE" not in _feed_text(study)
    study.sync(study.limited)
    assert "NEWNOTE" not in _history(study.limited)
    assert "NEWNOTE" not in text_of(study.limited)


def test_a_note_made_in_the_vault_after_the_upgrade_does_not_follow_the_record_back(
    study: Study,
):
    authority = study.authority
    seen = study.open_records[0]
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    study.sync(study.limited)
    _claim(study, seen, "harmless-delta")
    _watermark(authority)
    authority.note_svc.add(str(seen.id), f"{SECRET} VAULTNOTE")
    authority.commit()
    authority.record_svc.move("open", ids=[str(seen.id)])
    authority.commit()
    page = study.only_open.authority_svc.feed(0, 1000)
    # What was said while it was in the vault comes only with the record's whole
    # creation (a note entry made for that, never the original change).
    for e in page.entries:
        if e.entity_type == "note" and "VAULTNOTE" in str(e.to_dict()):
            assert e.action == "create" and e.id.version == 5


def test_a_note_on_a_record_in_sight_is_still_sent_after_the_upgrade(study: Study):
    authority = study.authority
    seen = study.open_records[0]
    _watermark(authority)
    authority.note_svc.add(str(seen.id), "a plain new note")
    authority.commit()
    assert "a plain new note" in _feed_text(study)
    study.sync(study.limited)
    assert "a plain new note" in text_of(study.limited)


def test_a_note_in_the_vault_with_no_legacy_trail_is_not_sent(study: Study):
    authority = study.authority
    seen = study.open_records[0]
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    study.sync(study.limited)
    _watermark(authority)
    authority.note_svc.add(str(seen.id), f"{SECRET} NEWNOTE")
    authority.commit()
    assert "NEWNOTE" not in _feed_text(study)


def test_a_device_behind_the_upgrade_is_still_told_a_record_left_its_sight(
    study: Study,
):
    authority, limited = study.authority, study.limited
    a, b = study.open_records[0], study.open_records[1]
    _claim(study, a, "claimed-while-open")  # stored as claimed, before the upgrade
    authority.record_svc.move("vault", ids=[str(a.id)])
    authority.record_svc.delete(str(b.id))
    authority.commit()
    _watermark(authority)
    study.sync(limited)
    assert str(a.id) not in held(limited, "record")
    got = limited.record_svc.records_repo.get_by_id(b.id, include_deleted=True)
    assert got is None or got.deleted_at is not None
    assert limited.sync_repo.meta().cursor == authority.sync_repo.head_seq()


def test_history_is_read_again_after_a_grant(
    study: Study, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sync_authority, "FEED_SCAN_MAX", 12)
    monkeypatch.setattr(sync_authority, "FEED_MAX", 4)
    monkeypatch.setattr(sync_service, "FEED_PAGE", 4)
    authority = study.authority
    vids = [
        authority.record_svc.add("vault", "encounter", {"site": f"V{i}"}).id
        for i in range(40)
    ]
    authority.commit()
    late = device(study.project, study.only_open, "late")
    connect(late)
    late._holder["inner"]._authority = scoped(
        authority, reads(study.open.id, study.vault.id)
    )
    late.sync_svc.sync()
    late.commit()
    late.commit()
    text = str([e.to_dict() for e in read_earlier(late)])
    assert all(str(v) in text for v in vids)


def test_a_limited_callers_page_size_is_honoured(
    study: Study, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sync_authority, "FEED_MAX", 7)
    monkeypatch.setattr(sync_authority, "FEED_SCAN_MAX", 21)
    authority = study.authority
    for i in range(30):
        authority.record_svc.add(
            "open" if i % 3 else "vault", "encounter", {"site": f"s{i}"}
        )
    authority.commit()
    svc = study.only_open.authority_svc

    def everything(limit: int) -> tuple[set[int], list[int]]:
        seen: set[int] = set()
        sizes: list[int] = []
        after = 0
        while True:
            page = svc.feed(after, limit)
            sizes.append(len(page.entries))
            if len(page.entries) > 1 and limit == 1:  # only an action, never cut
                assert page.entries[0].op
                assert {e.op for e in page.entries} == {page.entries[0].op}
            seen |= {e.hub_seq for e in page.entries}
            if not page.more:
                return seen, sizes
            assert page.through is not None and page.through > after
            after = page.through

    whole, _ = everything(500)
    got, sizes = everything(1)
    assert sizes.count(1) > len(sizes) // 2
    assert got == whole


def test_a_note_made_before_a_later_move_is_placed_by_that_moves_before(study: Study):
    authority = study.authority
    seen = study.open_records[1]
    _watermark(authority)
    authority.note_svc.add(str(seen.id), "made while in open")
    authority.commit()
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    assert "made while in open" in _feed_text(study)


def test_a_note_before_a_records_first_numbered_change_is_placed_where_it_was(
    study: Study,
):
    authority = study.authority
    seen = study.open_records[1]
    authority.note_svc.add(str(seen.id), "made while in open")
    authority.commit()
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    assert "made while in open" in _feed_text(study)


def test_synthetic_entries_do_not_borrow_the_ids_of_the_changes_they_stand_for(
    study: Study,
):
    authority = study.authority
    seen = study.open_records[1]
    authority.record_svc.move("vault", ids=[str(seen.id)])
    authority.commit()
    ids = {e.id for e in authority.authority_svc.feed(0, 1000).entries}
    authority.commit()
    page = study.only_open.authority_svc.feed(0, 1000)
    purges = [e for e in page.entries if e.action == "purge"]
    assert purges and all(e.id not in ids for e in purges)
