"""A blank copy of a project only downloads: files it pulled records for were
never here to send, so it never sends or asks about them. What the authority
lacks of them is the authority's to receive (arriving, then missing), and the
files are fetched only when the person chooses to keep every file."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import update

from civex.config import SyncConfig
from civex.db.models import Record
from civex.domain.sync import FILES
from civex.services.sync_worker import SyncWorker
from civex.testing.peers import connect, device


def _cite(laptop, record, contents: list[bytes], send: bool = True) -> list:
    if not any(f.name == "scan" for f in laptop.schema_svc.get("encounter").fields):
        laptop.schema_svc.add_field("encounter", "scan", "file")
        laptop.commit()
    refs = []
    for i, content in enumerate(contents):
        ref = laptop.file_svc.store_bytes(content, f"scan{i}.bin")
        rec = (
            record
            if i == 0
            else laptop.record_svc.add(
                "study", "encounter", {"site": f"s{i}", "depth": 1.0}
            )
        )
        laptop.record_svc.update(
            str(rec.id), {"site": f"s{i}", "depth": 1.0, "scan": ref.to_dict()}
        )
        refs.append(ref)
    laptop.commit()
    laptop.sync_svc.sync()
    if send:
        laptop.sync_svc.send_files()
    return refs


def _cite_ghost(laptop, name: str = "ghost") -> None:
    """A record citing a file no computer has uploaded (or even stored)."""
    laptop.record_svc.add(
        "study",
        "encounter",
        {
            "site": name,
            "depth": 1.0,
            "scan": {"sha256": "ab" * 32, "filename": f"{name}.bin", "size": 3},
        },
    )
    laptop.commit()
    laptop.sync_svc.sync()


def _clone(project, authority, name="tablet"):
    clone = device(project, authority, name, download_files="opened")
    assert connect(clone) == "joined"
    return clone


def _age_records(ctx, days: int) -> None:
    ctx.sync_repo._s.execute(
        update(Record).values(
            updated_at=datetime.now(timezone.utc) - timedelta(days=days)
        )
    )
    ctx.commit()


def test_a_fresh_clone_owes_nothing_and_never_sends(pair, project, authority):
    laptop, _, record = pair
    here = _cite(laptop, record, [b"one"])
    ghost = _cite(laptop, record, [b"two"], send=False)  # never uploaded
    assert here and ghost
    tablet = _clone(project, authority)

    assert tablet.sync_repo.count_unconfirmed() == 0
    seen: list = []
    report = tablet.sync_svc.send_files(progress=seen.append)
    assert (report.sent, seen) == (0, [])
    status = tablet.sync_svc.status()
    assert status.files_to_send == 0
    assert status.files_waiting is None


def test_what_this_computer_made_is_still_owed(pair):
    laptop, _, record = pair
    _cite(laptop, record, [b"mine"], send=False)
    assert laptop.sync_repo.count_unconfirmed() == 1
    assert laptop.sync_svc.status().files_to_send == 1


def test_files_the_authority_lacks_are_the_authoritys_not_ours(
    pair, project, authority
):
    laptop, _, record = pair
    _cite(laptop, record, [b"never uploaded"], send=False)
    tablet = _clone(project, authority)
    tablet.sync_svc.probe_files()  # the worker's look, once the copy is done

    status = tablet.sync_svc.status()
    assert (status.files_arriving, status.files_missing) == (1, 0)
    assert status.files_to_send == 0 and status.files_waiting is None

    _age_records(tablet, days=3)
    status = tablet.sync_svc.status()
    assert (status.files_arriving, status.files_missing) == (0, 1)
    assert status.files_to_send == 0 and status.files_waiting is None

    tablet.config.sync.arriving_hours = 0
    _age_records(tablet, days=0)
    assert tablet.sync_svc.status().files_missing == 1


def test_files_are_fetched_only_when_opened_until_chosen(pair, project, authority):
    laptop, _, record = pair
    _cite(laptop, record, [b"alpha", b"beta", b"gamma"])
    assert SyncConfig().download_files == "opened"
    tablet = _clone(project, authority)

    status = tablet.sync_svc.status()
    assert status.download_files == "opened"
    assert status.files_not_here == 3 and status.files_to_fetch == 0
    assert tablet.sync_svc.files_to_try() == 0

    tablet.sync_svc.set_download_files("all")  # the offer: Download all files
    status = tablet.sync_svc.status()
    assert status.download_files == "all"
    assert status.files_to_fetch == status.files_not_here == 3


def test_download_progress_counts_every_pass_in_bytes_and_rate(
    pair, project, authority
):
    laptop, _, record = pair
    contents = [b"a" * 1000, b"b" * 2000, b"c" * 3000]
    _cite(laptop, record, contents)
    tablet = _clone(project, authority)
    while not tablet.sync_svc.fetch_history(pages=1):
        pass
    tablet.sync_svc.set_download_files("all")

    class OneAtATime:
        """A pass that fetches a single file, as a slow link makes each."""

        def __init__(self, real) -> None:
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def fetch_files(self, **kw):
            return self._real.fetch_files(limit=1, **kw)

    shown: list = []
    worker = SyncWorker(lambda: tablet.config, lambda c: tablet, on_files=shown.append)
    ctx = SimpleNamespace(
        sync_svc=OneAtATime(tablet.sync_svc), sync_repo=tablet.sync_repo
    )
    for _ in range(3):
        worker._fetch_files(ctx)

    files = [p for p in shown if p is not None and p.phase == FILES]
    last = max(files, key=lambda p: p.done)
    assert (last.done, last.total) == (3, 3)
    assert last.bytes_done == sum(len(c) for c in contents)
    assert tablet.sync_svc.files_to_fetch() == 0


def test_the_look_at_the_server_waits_for_the_copy_and_asks_once(
    pair, project, authority
):
    laptop, _, record = pair
    here = _cite(laptop, record, [b"on the server"])
    _cite_ghost(laptop)
    assert here
    tablet = _clone(project, authority)
    assert tablet.sync_svc.status().files_not_here == 2

    tablet.sync_repo.set_cursor(-1)  # a copy still under way
    assert tablet.sync_svc.probe_files() == 0
    tablet.sync_repo.set_cursor(authority.sync_repo.head_seq())

    assert tablet.sync_svc.probe_files() == 2
    status = tablet.sync_svc.status()
    # What the server lacks is not offered for download.
    assert status.files_not_here == 1
    assert status.files_arriving + status.files_missing == 1
    assert tablet.sync_svc.probe_files() == 0  # nothing new to ask about


def test_an_export_from_a_clone_fetches_the_files_it_lacks(
    pair, project, authority, tmp_path
):
    import json
    import zipfile

    laptop, _, record = pair
    kept = _cite(laptop, record, [b"fetched for the export"])[0]
    _cite_ghost(laptop)
    tablet = _clone(project, authority)
    assert not tablet.file_svc.exists(kept.sha256)

    out = tmp_path / "out.zip"
    plan = tablet.bundle_svc.export(out)
    assert tablet.file_svc.exists(kept.sha256)
    with zipfile.ZipFile(out) as zf:
        assert f"files/{kept.sha256}" in zf.namelist()
        manifest = json.loads(zf.read("bundle.json"))
    assert len(manifest["files"]["missing"]) == 1
    assert (plan.files_unreachable, plan.files_not_on_server) == (1, 1)
