"""An action cut across feed pages is held or applied as a whole: the device
decides once the action's last entry has arrived, never page by page."""

from __future__ import annotations

import uuid
from dataclasses import replace

from civex.db.models import AuditLog


def _action(pair, authority, unsent_on_last: bool):
    laptop, phone, _ = pair
    ids = [
        str(
            laptop.record_svc.add(
                "study", "encounter", {"site": f"h{i}", "depth": 1.0}
            ).id
        )
        for i in range(10)
    ]
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    start = authority.sync_repo.head_seq()
    for i, rid in enumerate(ids):
        laptop.record_svc.update(rid, {"depth": 50.0 + i})
    laptop.commit()
    laptop.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    authority.sync_repo._s.query(AuditLog).filter(AuditLog.hub_seq > start).update(
        {"op_id": uuid.uuid4()}, synchronize_session=False
    )
    authority.commit()
    if unsent_on_last:
        phone.record_svc.update(ids[-1], {"depth": 7.0})
        phone.commit()
    return phone, ids


def _cut(phone, size: int) -> list[int]:
    """The phone's feed, served `size` entries at a time (an action cut across
    pages); answers how many entries each page had."""
    transport = phone.sync_svc._transport()
    real = transport.feed
    sizes: list[int] = []

    def feed(after, limit):
        page = real(after, 1000)
        taken = page.entries[:size]
        sizes.append(len(taken))
        return replace(
            page,
            entries=taken,
            more=len(page.entries) > size or page.more,
            through=None,
        )

    transport.feed = feed
    return sizes


def test_a_device_holds_an_action_cut_across_pages(pair, authority):
    phone, ids = _action(pair, authority, unsent_on_last=True)
    sizes = _cut(phone, 3)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert len(sizes) > 2  # it really was cut
    assert phone.record_svc.get(ids[0]).data["depth"] == 1.0  # all of it held


def test_an_action_cut_across_pages_is_applied_whole_when_nothing_holds_it(
    pair, authority
):
    phone, ids = _action(pair, authority, unsent_on_last=False)
    sizes = _cut(phone, 3)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert len(sizes) > 2
    assert [phone.record_svc.get(i).data["depth"] for i in ids] == [
        50.0 + i for i in range(10)
    ]
    assert phone.sync_repo.meta().cursor == authority.sync_repo.head_seq()


# -- a big action, from disk --------------------------------------------------


def _fake_action(pair, authority, n: int):
    """`n` created records as one action, made from a real entry; the phone is
    told of them through a feed of our own (pages of 1000, cut mid-action)."""
    import copy
    from dataclasses import replace as _replace

    laptop, phone, _ = pair
    start = authority.sync_repo.head_seq()
    laptop.record_svc.add("study", "encounter", {"site": "t", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    [template] = [
        e
        for e in authority.sync_repo.entries_after(start, 50)[0]
        if e.entity_type == "record" and e.action == "create"
    ]
    phone.sync_svc.sync()  # caught up to where the action will start
    base = authority.sync_repo.head_seq()
    op = str(uuid.uuid4())
    entries = []
    for i in range(n):
        rid = uuid.uuid4()
        data = copy.deepcopy(template.new_data)
        data["id"] = str(rid)
        data["data"] = {**data["data"], **{k: f"x{i}" for k in list(data["data"])[:1]}}
        entries.append(
            _replace(
                template,
                id=uuid.uuid4(),
                entity_id=rid,
                new_data=data,
                hub_seq=base + 1 + i,
                op=op,
            )
        )
    return phone, entries, base


def _serve(phone, entries, base, page=1000, stop_after=None):
    from civex.domain.sync import FeedPage

    transport = phone.sync_svc._transport()
    calls = {"n": 0}

    def feed(after, limit):
        calls["n"] += 1
        if stop_after is not None and calls["n"] > stop_after:
            from civex.domain.sync import SyncError

            raise SyncError("the connection dropped")
        lo = after - base
        chunk = entries[lo : lo + page]
        return FeedPage(
            entries=chunk,
            head_seq=base + len(entries),
            more=lo + page < len(entries),
            through=chunk[-1].hub_seq if chunk else None,
        )

    transport.feed = feed


def test_a_six_thousand_entry_action_is_applied_whole_from_disk_in_bounded_memory(
    pair, authority
):
    """The mechanism, not the cost of applying (that is the same per entry as
    any pull's): every step is a no-op here, so what is measured is what the
    pull keeps in memory while an action of 6,000 entries is cut over pages."""
    import tracemalloc

    from civex.db.models import AuditLog

    phone, entries, base = _fake_action(pair, authority, 6_000)
    _serve(phone, entries, base)
    svc = object.__getattribute__(phone.sync_svc, "_svc")
    steps: list[int] = []
    svc._replay = lambda thing, seq, isolate=True: steps.append(seq)
    states_seen: list[int] = []
    repo_cls = type(phone.sync_repo)
    real = repo_cls.arriving_entries

    def watching(self, op, after, limit, **kwargs):
        if not states_seen:  # the first read: every entry is on disk by now
            states_seen.append(
                self._s.query(AuditLog)
                .filter(AuditLog.apply_state == "arriving")
                .count()
            )
        return real(self, op, after, limit, **kwargs)

    repo_cls.arriving_entries = watching  # type: ignore[method-assign]
    tracemalloc.start()
    try:
        phone.sync_svc._pull(phone.sync_svc._transport())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        repo_cls.arriving_entries = real  # type: ignore[method-assign]
    phone.commit()
    assert states_seen == [6_000]  # decided only after the last arrived
    assert len(steps) == 6_000
    assert phone.sync_repo.arriving_action() == (None, False)
    assert phone.sync_repo.meta().cursor == base + 6_000
    applied = (
        phone.sync_repo._s.query(AuditLog)
        .filter(AuditLog.hub_seq > base, AuditLog.apply_state == "applied")
        .count()
    )
    assert applied == 6_000
    assert peak < 40 * 1024 * 1024, peak


def test_a_stop_in_the_middle_of_an_action_resumes_from_disk(pair, authority):
    phone, entries, base = _fake_action(pair, authority, 2_500)
    _serve(phone, entries, base, page=1000, stop_after=2)  # two pages, then it drops
    import pytest

    from civex.domain.sync import SyncError

    with pytest.raises(SyncError, match="dropped"):
        phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    op, held = phone.sync_repo.arriving_action()
    assert op == entries[0].op and held is False
    assert phone.sync_repo.meta().cursor == base + 2_000  # past what is on disk
    before = len(phone.record_svc.find("study", "encounter", limit=5_000))
    assert before < 100  # none of the action applied yet
    _serve(phone, entries, base)  # a new pass, from the stored cursor
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.sync_repo.arriving_action() == (None, False)
    assert len(phone.record_svc.find("study", "encounter", limit=5_000)) >= 2_500


def test_an_entry_on_the_last_page_holds_the_whole_action_on_disk(pair, authority):
    phone, entries, base = _fake_action(pair, authority, 2_500)
    laptop, _, _ = pair
    # the phone has an unsent edit to the very last record of the action
    last = entries[-1]
    from civex.domain.sync import SyncEntry

    assert isinstance(last, SyncEntry)
    from civex.db.models import Record

    phone.record_svc  # (the record doesn't exist yet: make it, then edit it)
    created = phone.record_svc.add("study", "encounter", {"site": "mine", "depth": 1.0})
    phone.commit()
    phone.sync_svc.sync()
    phone.record_svc.update(str(created.id), {"depth": 9.0})
    phone.commit()
    # the action's last entry touches that record
    import copy
    from dataclasses import replace as _replace

    data = copy.deepcopy(last.new_data)
    data["id"] = str(created.id)
    entries[-1] = _replace(last, entity_id=created.id, new_data=data, action="update")
    _serve(phone, entries, base)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    held = phone.sync_repo.held_entries()
    assert len(held) >= 2_499 and {e.op for e in held} == {entries[0].op}
    assert phone.sync_repo.arriving_action() == (None, False)
    from civex.db.models import AuditLog

    applied = (
        phone.sync_repo._s.query(AuditLog)
        .filter(
            AuditLog.op_id == uuid.UUID(entries[0].op),
            AuditLog.apply_state == "applied",
        )
        .count()
    )
    assert applied == 0  # nothing of the action was applied
    assert Record is not None


# -- the indexes are used -----------------------------------------------------


def test_the_unsettled_and_action_queries_use_their_partial_indexes(pair, authority):
    """On SQLite a partial index is used only when the query repeats its
    condition: ask the database, with the statements the repository sends."""
    from sqlalchemy import event

    phone = pair[1]
    repo = phone.sync_repo
    engine = repo._s.get_bind()
    seen: list[tuple[str, object]] = []

    def capture(conn, cursor, statement, parameters, context, many):
        if "audit_log" in statement and not statement.startswith("EXPLAIN"):
            seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        repo.arriving_action()
        repo.arriving_entries(str(uuid.uuid4()), 0, 500)
        repo.arriving_entries(str(uuid.uuid4()), 0, 500, state="settling", upto=9)
        repo.held_entries()
        repo.set_arriving(str(uuid.uuid4()), ("arriving",), "held")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(seen) >= 5
    plans = []
    for statement, parameters in seen[-5:]:
        rows = (
            repo._s.connection()
            .exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)
            .fetchall()
        )
        plans.append(" | ".join(str(r[-1]) for r in rows))
    for plan in plans:
        assert "ix_audit_log_unsettled" in plan or "ix_audit_log_op" in plan, plan
        assert "SCAN audit_log" not in plan.replace("SCAN audit_log USING", ""), plan


# -- the half-applied action, a stale decision, and the edges ------------------


def test_a_staged_entry_is_never_a_step_of_a_replay(pair, authority):
    """`_replay` of a thing must not apply the entries of an action that has not
    all arrived: not as `arriving`, not as `arrhold`."""
    from civex.db.models import AuditLog

    phone, entries, base = _fake_action(pair, authority, 1_200)
    _serve(phone, entries, base, page=1_000, stop_after=1)
    import pytest

    from civex.domain.sync import SyncError

    with pytest.raises(SyncError):
        phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    repo = phone.sync_repo
    staged = entries[0]
    assert repo.arriving_action()[0] == staged.op
    assert repo.numbered_entries("record", staged.entity_id, 0) == []
    repo._s.query(AuditLog).filter(AuditLog.hub_seq > base).update(
        {"apply_state": "arrhold"}
    )
    repo._s.flush()
    assert repo.numbered_entries("record", staged.entity_id, 0) == []


def test_a_hold_is_decided_again_at_settle_after_the_person_edited(pair, authority):
    """The first pass staged an action (nothing of the person's own in the way);
    before the next pass they edited a record the action touches: a pass pulls
    before it pushes, so the action must be held, and the edit kept."""
    laptop, phone, _ = pair
    phone, entries, base = _fake_action(pair, authority, 1_200)
    mine = phone.record_svc.add("study", "encounter", {"site": "mine", "depth": 1.0})
    phone.commit()
    phone.sync_svc.sync()
    from dataclasses import replace as _replace

    # an entry on the first page changes `mine` (an update, as the authority has it)
    base = authority.sync_repo.head_seq()
    entries = [
        _replace(e, hub_seq=e.hub_seq + (base - entries[0].hub_seq + 1))
        for e in entries
    ]
    entries[5] = _replace(
        entries[5], entity_id=mine.id, action="update", new_data={"id": str(mine.id)}
    )
    _serve(phone, entries, base, page=1_000, stop_after=1)
    import pytest

    from civex.domain.sync import SyncError

    with pytest.raises(SyncError):
        phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.sync_repo.arriving_action() == (entries[0].op, False)  # clean so far
    phone.record_svc.update(str(mine.id), {"depth": 9.0})  # the person edits
    phone.commit()
    _serve(phone, entries, base, page=1_000)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.sync_repo.arriving_action() == (None, False)
    held = phone.sync_repo.held_entries()
    assert len(held) == 1_200 and {e.op for e in held} == {entries[0].op}
    assert phone.record_svc.get(str(mine.id)).data["depth"] == 9.0


def test_a_resume_with_a_hold_already_decided_holds_the_whole_action(pair, authority):
    phone, entries, base = _fake_action(pair, authority, 1_200)
    mine = phone.record_svc.add("study", "encounter", {"site": "mine", "depth": 1.0})
    phone.commit()
    phone.sync_svc.sync()
    from dataclasses import replace as _replace

    shift = authority.sync_repo.head_seq() - entries[0].hub_seq + 1
    base = authority.sync_repo.head_seq()
    entries = [_replace(e, hub_seq=e.hub_seq + shift) for e in entries]
    # an entry on the FIRST page changes `mine`, which has an unsent edit
    entries[5] = _replace(
        entries[5], entity_id=mine.id, action="update", new_data={"id": str(mine.id)}
    )
    phone.record_svc.update(str(mine.id), {"depth": 9.0})
    phone.commit()
    _serve(phone, entries, base, page=1_000, stop_after=1)
    import pytest

    from civex.domain.sync import SyncError

    with pytest.raises(SyncError):
        phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.sync_repo.arriving_action() == (entries[0].op, True)  # arrhold
    _serve(phone, entries, base, page=1_000)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.sync_repo.arriving_action() == (None, False)
    assert len(phone.sync_repo.held_entries()) == 1_200
    assert phone.record_svc.get(str(mine.id)).data["depth"] == 9.0


def test_an_empty_more_page_with_no_progress_ends_the_pull(pair, authority):
    from civex.domain.sync import FeedPage

    phone, entries, base = _fake_action(pair, authority, 1_200)
    _serve(phone, entries, base, page=1_000)
    transport = phone.sync_svc._transport()
    real = transport.feed
    calls = {"n": 0}

    def feed(after, limit):
        calls["n"] += 1
        assert calls["n"] < 10, "asked again and again"
        if after >= base + 1_000:
            return FeedPage([], base + 1_200, more=True, through=None)
        return real(after, limit)

    transport.feed = feed
    phone.sync_svc._pull(transport)
    phone.commit()
    assert calls["n"] == 2
    assert phone.sync_repo.arriving_action()[0] == entries[0].op  # still arriving
    assert phone.sync_repo.meta().cursor == base + 1_000


def test_a_page_that_ends_exactly_where_an_action_ends(pair, authority):
    from dataclasses import replace as _replace

    phone, entries, base = _fake_action(pair, authority, 300)
    extra = [
        _replace(
            e,
            id=uuid.uuid4(),
            op=None,
            hub_seq=base + 301 + i,
            entity_id=uuid.UUID(int=i + 1),
            new_data={**(e.new_data or {}), "id": str(uuid.UUID(int=i + 1))},
        )
        for i, e in enumerate(entries[:3])
    ]
    everything = entries + extra
    _serve(phone, everything, base, page=300)  # page 1 = the whole action, more
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.sync_repo.arriving_action() == (None, False)
    assert phone.sync_repo.meta().cursor == base + 303
    from civex.db.models import AuditLog

    states = {
        s
        for (s,) in phone.sync_repo._s.query(AuditLog.apply_state)
        .filter(AuditLog.hub_seq > base)
        .distinct()
    }
    assert states == {"applied"}


def test_server_hung_up_works_for_a_descriptor_past_1024():
    import os
    import socket
    import sys

    import pytest

    if sys.platform == "win32":
        pytest.skip("descriptors are not small integers on Windows")
    import resource

    from civex.services.http_wire import _server_hung_up

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if hard != resource.RLIM_INFINITY and hard < 1_200:
        pytest.skip("cannot raise the descriptor limit")
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, 1_200), hard))
    a, b = socket.socketpair()
    high = os.dup2(a.fileno(), 1_100)
    sock = socket.socket(fileno=high)
    try:
        assert sock.fileno() >= 1_024
        assert _server_hung_up(sock) is False  # nothing to read: still good
        b.close()  # the other side hangs up
        assert _server_hung_up(sock) is True
    finally:
        sock.close()
        a.close()
