"""The authority answers a push, and `missing_files`, in few statements: what a
push asks one change at a time is read once, and `missing_files` is one lookup.
The answers stay the ones the slow way gave."""

from __future__ import annotations

import collections

from sqlalchemy import event


def _count(ctx):
    seen: collections.Counter[str] = collections.Counter()

    def on(conn, cursor, statement, *args):  # noqa: ANN001, ANN002
        seen[statement.split(None, 1)[0].upper()] += 1

    engine = ctx._session.get_bind()
    event.listen(engine, "before_cursor_execute", on)
    return seen, lambda: event.remove(engine, "before_cursor_execute", on)


def _many_records(ctx, n: int) -> list:
    return [
        ctx.record_svc.add("study", "encounter", {"site": f"s{i}", "depth": 1.0}).id
        for i in range(n)
    ]


def test_a_push_costs_a_fixed_few_statements_per_change(pair, authority):
    laptop, _, _ = pair
    laptop.sync_svc.sync()
    ids = _many_records(laptop, 40)
    laptop.commit()
    seen, stop = _count(authority)
    laptop.sync_svc.sync()
    stop()
    per_entry = sum(seen.values()) / 40
    assert per_entry <= 11, (per_entry, seen)  # 17 before
    assert seen["UPDATE"] <= 40 + 5  # the feed's counter, once a change

    for i, rid in enumerate(ids):
        laptop.record_svc.update(str(rid), {"site": f"e{i}", "depth": 2.0})
    laptop.commit()
    seen, stop = _count(authority)
    laptop.sync_svc.sync()
    stop()
    assert sum(seen.values()) / 40 <= 15, seen  # 20 before


def test_a_push_repeated_is_answered_from_what_was_sent(pair, authority):
    laptop, _, _ = pair
    laptop.sync_svc.sync()
    _many_records(laptop, 3)
    laptop.commit()
    laptop.sync_svc.sync()
    head = authority.sync_repo.head_seq()
    laptop.sync_svc.sync()
    assert authority.sync_repo.head_seq() == head  # nothing taken twice


def test_missing_files_is_one_lookup_and_agrees_with_asking_one_by_one(pair, authority):
    laptop, _, record = pair
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    refs = [
        laptop.file_svc.store_bytes(f"file {i}".encode(), f"f{i}.bin") for i in range(5)
    ]
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": refs[0].to_dict()}
    )
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()  # the first is up; the others are not
    shas = [r.sha256 for r in refs] + ["ab" * 32, "cd" * 32]
    seen, stop = _count(authority)
    lacking = laptop._holder["inner"].missing_files(shas)
    stop()
    assert sum(seen.values()) <= 6  # 1000 hashes used to be 1000 statements
    assert set(lacking) == {s for s in shas if not authority.file_svc.exists(s)}
    assert refs[0].sha256 not in lacking and refs[1].sha256 in lacking
    assert authority.file_svc.exists_many(shas) == {refs[0].sha256}
