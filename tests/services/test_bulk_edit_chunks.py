"""A bulk edit at scale: the plan is worked out over the set and says what
the edit then does; the edit is saved a chunk at a time, each chunk whole and
in its own short transaction, so another save goes in between two; stopped
half way it leaves whole records and is finished by running it again."""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import event, text

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.domain.audit_diff import entry_snapshots
from civex.domain.query import RecordQuery
from civex.services import record_service


@pytest.fixture()
def trials(ctx: AppContext, make_schema, make_collection):
    make_schema("site", fields=[("name", "string")])
    make_schema("trial", fields=[("subject", "string")], parent="site")
    ctx.schema_svc.add_field("trial", "depth", "integer", restrictions={"max": 100})
    ctx.schema_svc.add_field("trial", "status", "string")
    ctx.schema_svc.add_field("trial", "code", "string")
    ctx.commit()
    make_collection("study")
    site = ctx.record_svc.add("study", "site", {"name": "a"})
    ctx.commit()

    def more(n: int, **values) -> list[str]:
        made = [
            ctx.record_svc.add(
                "study",
                "trial",
                {"subject": f"t{time.monotonic_ns()}-{i}", "status": "new", **values},
                parent_record_id=str(site.id),
            )
            for i in range(n)
        ]
        ctx.commit()
        return [str(r.id) for r in made]

    return site, more


def _statements(ctx: AppContext, work) -> list[str]:
    seen: list[str] = []
    engine = ctx._session.get_bind()

    def count(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        work()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return seen


def _status(ctx: AppContext, ids: list[str]) -> list[str]:
    return [ctx.record_svc.get(i).data.get("status") for i in ids]


# -- the plan and the edit agree ----------------------------------------------


def test_the_plan_says_what_the_edit_does_on_a_mixed_selection(ctx: AppContext, trials):
    """Records that already hold the value, a kind with no such field of its
    own, a value the field won't take, a uniqueness key only one can take,
    and a change to two fields that some records half hold."""
    site, more = trials
    ids = more(6) + more(3, status="done", depth=5) + more(2, depth=5)
    everything = [*ids, str(site.id)]
    ctx.schema_svc.set_unique_keys("trial", [["code"]])
    ctx.commit()
    for changes in (
        {"status": "done"},
        {"status": "done", "depth": 5},
        {"depth": 500},  # more than the field allows
        {"status": None},  # cleared
        {"code": "one-of-a-kind"},  # a key: the first takes it, the rest can't
        {"name": "renamed"},  # only the site has it; the trials inherit it
    ):
        plan = ctx.record_svc.plan_bulk_edit(changes, ids=everything)
        asked = ctx.record_svc.plan_bulk_edit(
            changes, query=RecordQuery(dataset="study")
        )
        result = ctx.record_svc.bulk_edit(changes, ids=everything)
        ctx.rollback()

        said = (plan.changing, plan.unchanged, plan.skipped)
        assert said == (result.changed, result.unchanged, result.skipped), changes
        assert said == (asked.changing, asked.unchanged, asked.skipped), changes
        assert plan.records == len(everything)
        if "code" not in changes:
            # (For a key, the plan says another chosen record would take the
            # value; the edit, that one by then holds it.)
            assert sorted(s.reason for s in plan.skipped_records) == sorted(
                s.reason for s in result.skipped_records
            ), changes
        assert all(s.name for s in plan.skipped_records)


# -- cost ----------------------------------------------------------------------


def test_planning_costs_the_same_however_many_records(ctx: AppContext, trials):
    _, more = trials
    by_ids: list[int] = []
    by_query: list[int] = []
    ids: list[str] = []
    for n in (4, 40, 160):
        ids += more(n - len(ids))
        by_ids.append(
            len(
                _statements(
                    ctx, lambda: ctx.record_svc.plan_bulk_edit({"status": "x"}, ids=ids)
                )
            )
        )
        by_query.append(
            len(
                _statements(
                    ctx,
                    lambda: ctx.record_svc.plan_bulk_edit(
                        {"status": "x", "depth": 3},
                        query=RecordQuery(dataset="study", schema="trial"),
                    ),
                )
            )
        )
    assert len(set(by_ids)) == 1 and by_ids[0] <= 8, by_ids
    assert len(set(by_query)) == 1 and by_query[0] <= 10, by_query


def test_a_chunk_costs_the_same_however_many_records_are_in_it(
    ctx: AppContext, trials, monkeypatch: pytest.MonkeyPatch
):
    """A chunk is a read of its records, one statement saving them and one
    for their history entries: not a save, two catalogs and an entry each."""
    _, more = trials
    monkeypatch.setattr(record_service, "BULK_EDIT_PAGE", 50)

    def cost(n: int, value: str) -> tuple[int, list[str]]:
        ids = more(n)
        seen = _statements(
            ctx, lambda: ctx.record_svc.bulk_edit({"status": value}, ids=ids)
        )
        ctx.commit()
        assert set(_status(ctx, ids)) == {value}
        return len(seen), seen

    one_small, _ = cost(5, "a")
    one_full, seen = cost(50, "b")
    three, _ = cost(150, "c")

    assert one_full == one_small  # 5 records or 50: the same statements
    per_chunk = (three - one_full) / 2
    assert per_chunk <= 4, (per_chunk, seen)
    writes = [s for s in seen if s.lstrip().upper().startswith(("UPDATE", "INSERT"))]
    assert len(writes) <= 4, writes  # the records, their entries, the batch


# -- one event, however many chunks ----------------------------------------------


def test_every_chunk_is_in_one_event_and_is_undone_as_one(
    ctx: AppContext, trials, monkeypatch: pytest.MonkeyPatch
):
    _, more = trials
    monkeypatch.setattr(record_service, "BULK_EDIT_PAGE", 3)
    ids = more(8)

    with ctx.chunked_writes() as turn:
        chunks = 0
        for _ in ctx.record_svc.bulk_edit_chunks({"status": "checked"}, ids=ids):
            turn()
            chunks += 1
    assert chunks == 3

    events, _ = ctx.history_svc.events(
        where={"field": "how", "op": "eq", "value": "edit"}, limit=5
    )
    assert len(events) == 1 and events[0].batch.label == "status"
    batch = events[0].batch.id
    entries = ctx.history_svc.page(batch_id=batch, limit=20)
    # An entry each, as a save writes: its own action, so one sent to a server
    # between two chunks splits nothing.
    assert {str(e.entity_id) for e in entries} == set(ids)
    assert {e.action for e in entries} == {"update"}
    assert [c["field"] for e in entries for c in e.changes] == ["status"] * 8
    shared = ctx._session.execute(
        text(
            "select count(*) from (select op_id from audit_log where action = 'update' and op_id is "
            "not null group by op_id having count(*) > 1)"
        )
    ).scalar()
    assert shared == 0  # no action spans two records, let alone two chunks

    # Each entry is the record as it was saved, the time of the save included:
    # these entries are what a sync sends.
    stored = {str(r.id): r for r in ctx.record_svc.get_many(ids, as_stored=True)}
    for entry in entries:
        record = stored[str(entry.entity_id)]
        before, after = entry_snapshots(entry.old_data, entry.new_data, entry.delta)
        assert after["updated_at"] == record.to_dict()["updated_at"]
        assert before["updated_at"] != after["updated_at"]
        held = ctx.record_svc._records.get_by_id(record.id).data
        assert after["data"] and all(held[k] == v for k, v in after["data"].items())

    undone = ctx.history_svc.revert_batch(batch, dry_run=False)
    ctx.commit()
    assert undone.applied == 8 and set(_status(ctx, ids)) == {"new"}


def test_an_edit_alone_never_waits_for_anyone(
    ctx: AppContext, trials, monkeypatch: pytest.MonkeyPatch
):
    """It gives way only when another writer asked: its own writes ask
    nothing, so by itself it goes straight from one chunk to the next."""
    from civex import context

    _, more = trials
    monkeypatch.setattr(record_service, "BULK_EDIT_PAGE", 3)
    ids = more(10)
    waited: list[float] = []
    monkeypatch.setattr(context.time, "sleep", waited.append)

    with ctx.chunked_writes() as turn:
        for _ in ctx.record_svc.bulk_edit_chunks({"status": "checked"}, ids=ids):
            turn()

    assert waited == [] and set(_status(ctx, ids)) == {"checked"}


# -- stopping and going on -------------------------------------------------------


def test_an_edit_stopped_half_way_leaves_whole_records_and_is_finished_by_running_it_again(
    ctx: AppContext, trials, monkeypatch: pytest.MonkeyPatch
):
    _, more = trials
    monkeypatch.setattr(record_service, "BULK_EDIT_PAGE", 10)
    ids = more(35)
    changes = {"status": "checked", "depth": 7}

    with ctx.chunked_writes() as turn:
        chunks = ctx.record_svc.bulk_edit_chunks(changes, ids=ids)
        for done, _ in enumerate(chunks, 1):
            turn()
            if done == 2:
                chunks.close()  # stopped: cancelled, or the lights went out
                break
    ctx.rollback()

    with build_local_context(load_config()) as fresh:
        held = [fresh.record_svc.get(i).data for i in ids]
    both = [d for d in held if d.get("status") == "checked" and d.get("depth") == 7]
    neither = [d for d in held if d.get("status") == "new" and "depth" not in d]
    assert (len(both), len(neither)) == (20, 15)  # no record half changed

    again = ctx.record_svc.plan_bulk_edit(changes, ids=ids)
    assert (again.changing, again.unchanged) == (15, 20)
    result = ctx.record_svc.bulk_edit(changes, ids=ids)
    ctx.commit()
    assert (result.changed, result.unchanged) == (15, 20)
    assert set(_status(ctx, ids)) == {"checked"}


# -- other saves go in meanwhile ---------------------------------------------------


def test_another_save_goes_in_while_a_big_edit_runs(
    ctx: AppContext, trials, monkeypatch: pytest.MonkeyPatch
):
    """The edit never holds the database for longer than a chunk, and gives
    way when another writer asks: a save from another session, made while a
    few thousand records are being changed, is in within about a chunk."""
    _, more = trials
    monkeypatch.setattr(record_service, "BULK_EDIT_PAGE", 100)
    ids = more(3000)  # thirty chunks
    (other,) = more(1)
    running = threading.Event()
    finished = threading.Event()
    failed: list[BaseException] = []

    def edit() -> None:
        try:
            with build_local_context(load_config()) as editing:
                with editing.chunked_writes() as turn:
                    for _ in editing.record_svc.bulk_edit_chunks(
                        {"status": "checked"}, ids=ids
                    ):
                        turn()
                        running.set()
        except BaseException as e:  # noqa: BLE001 - reported by the test
            failed.append(e)
        finally:
            running.set()
            finished.set()

    waits: list[float] = []
    during = 0
    # The saving session is ready before the edit starts, so its first save
    # is asked for while the edit still has most of its chunks to go.
    with build_local_context(load_config()) as saving:
        worker = threading.Thread(target=edit)
        worker.start()
        assert running.wait(30)  # its first chunk is in
        for n in range(500):
            if finished.is_set():
                break
            began = time.monotonic()
            saving.record_svc.patch(other, {"code": f"saved {n}"})
            saving.commit()
            waits.append(time.monotonic() - began)
            during += not finished.is_set()
        worker.join(60)

    assert not failed, failed
    assert during >= 1, "no save was made while the edit ran"
    assert max(waits) < 2.0, sorted(waits)[-3:]
    assert set(_status(ctx, ids)) == {"checked"}
    assert ctx.record_svc.get(other).data["code"].startswith("saved ")
