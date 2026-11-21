"""Releases (`civex.domain.release`): a small bundle of records whose files are
referenced, never copied (the release owns them in `file_references`); the
content hash; verify and deep verify; citations; corrections, withdrawal and
yank in history; what clean-up keeps and frees; file moves carrying a
release's pointers; getting the files out through FileAccessService; what
changed since; who may; and what it costs."""

from __future__ import annotations

import io
import json
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event, select

from civex.config import FileConfigStore, load_config_at
from civex.context import AppContext, build_context, build_local_context
from civex.db.models import AuditLog, FileReference
from civex.domain import permissions as p
from civex.domain import release as rules
from civex.domain.exceptions import (
    AlreadyExistsError,
    NotAllowedError,
    ValidationError,
)
from civex.domain.permissions import Permissions
from civex.domain.query import RecordQuery
from civex.domain.transfers import KIND_CONSOLIDATE, TransferSpec
from civex.project import Project, scaffold_project
from civex.repositories.local.file_ref_repo import LocalFileReferenceRepository
from civex.services.release_service import BAG_MANIFEST, ReleaseScope
from civex.services.transfer_engine import run_transfer


@pytest.fixture()
def study(ctx: AppContext):
    ctx.schema_svc.create("site")
    ctx.schema_svc.add_field("site", "name", "string")
    ctx.schema_svc.add_field("site", "photo", "file")
    ctx.schema_svc.create("sample", parent="site")
    ctx.schema_svc.add_field("sample", "depth", "float")
    ctx.dataset_svc.create("north")
    ctx.dataset_svc.create("south")
    photo = ctx.file_svc.store_bytes(b"a photo", "p.jpg")
    a = ctx.record_svc.add("north", "site", {"name": "A", "photo": photo.to_dict()})
    ctx.record_svc.add("north", "sample", {"depth": 1.0}, parent_record_id=str(a.id))
    ctx.record_svc.add("north", "sample", {"depth": 2.0}, parent_record_id=str(a.id))
    ctx.record_svc.add("south", "site", {"name": "B"})
    ctx.commit()
    return {"a": a, "photo": photo}


def _make(ctx: AppContext, name: str = "v1", **kw):
    made = ctx.release_svc.create(
        name,
        kw.pop("title", "Seal survey"),
        authors=kw.pop("authors", [{"name": "Ada Lovelace"}]),
        **kw,
    )
    ctx.commit()
    return made


def _members(ctx: AppContext, release) -> dict[str, bytes]:
    with ctx.release_svc.open_bundle(release.name) as (_, f):
        with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
            return {n: zf.read(n) for n in zf.namelist()}


def _owned(ctx: AppContext, release) -> dict[str, str | None]:
    return {
        sha: volume
        for sha, volume in ctx._session.execute(
            select(FileReference.sha256, FileReference.volume).where(
                FileReference.release_id == release.id
            )
        )
    }


def test_a_release_holds_records_and_owns_the_files_where_they_are(ctx, study):
    made = _make(ctx, licence="CC-BY-4.0", doi="https://doi.org/10.1234/abcd")
    assert made.content_hash.startswith(rules.HASH_PREFIX)
    assert made.doi == "10.1234/abcd"
    assert made.counts["records"] == 4 and made.counts["files"] == 1
    assert made.scope == {} and made.local_seq and made.feed_seq is None
    members = _members(ctx, made)
    assert {
        "bundle.json",
        "records.jsonl",
        rules.RELEASE_JSON,
        rules.CITATION_CFF,
    } <= set(members)
    # No file is copied into it: it owns them where they are, and its bundle.
    assert not any(n.startswith("files/") for n in members)
    owned = _owned(ctx, made)
    photo = study["photo"].sha256
    assert set(owned) == {photo, made.bundle_sha256}
    # Each points at the copy its records point at.
    used = ctx.file_svc._store.copies_used([study["a"].id])
    assert owned[photo] == used[(study["a"].id, photo)]
    assert b"location" not in members["records.jsonl"]
    assert ctx.file_info_svc.info(photo).releases == ["v1"]


def test_making_a_release_asks_no_drive_where_a_file_is(ctx, study, monkeypatch):
    store = ctx.file_svc._store

    def refuse(*_, **__):
        raise AssertionError("a drive was asked about a file")

    for name in ("locate_volumes", "copies_used", "open", "get"):
        monkeypatch.setattr(store, name, refuse)
    made = _make(ctx)
    assert made.counts["files"] == 1


def test_the_hash_covers_records_and_the_files_they_cite(ctx, study):
    first = _make(ctx, "v1")
    second = _make(ctx, "v2", title="Another title")
    assert first.content_hash == second.content_hash
    assert first.bundle_sha256 != second.bundle_sha256  # the zips differ
    # Another file under the same name changes the hash; no bytes are read.
    other = ctx.file_svc.store_bytes(b"another photo", "p.jpg")
    ctx.record_svc.update(str(study["a"].id), {"photo": other.to_dict()})
    ctx.commit()
    assert _make(ctx, "v3").content_hash != first.content_hash


def test_scope_collections_a_query_or_chosen_records(ctx, study):
    north = _make(ctx, "north", scope=ReleaseScope(collections=["north"]))
    assert north.counts["records"] == 3 and north.scope == {"collections": ["north"]}
    assert set(_owned(ctx, north)) == {study["photo"].sha256, north.bundle_sha256}
    deep = _make(
        ctx,
        "deep",
        scope=ReleaseScope(
            query=RecordQuery(
                dataset="north",
                schema="sample",
                filter_tree={"field": "depth", "op": "gt", "value": 1.5},
            )
        ),
    )
    # The one sample listed, and the site above it so it reads back whole.
    assert deep.counts["records"] == 2 and deep.scope["query"]["schema"] == "sample"
    assert study["photo"].sha256 in _owned(ctx, deep)
    b = ctx.record_svc.find("south", "site", filters=["name=B"])[0]
    picked = _make(ctx, "picked", scope=ReleaseScope(records=[str(b.id)]))
    assert picked.counts["records"] == 1
    assert set(_owned(ctx, picked)) == {picked.bundle_sha256}
    plan = ctx.release_svc.plan(ReleaseScope(collections=["north"]))
    assert plan.records == 3 and plan.collections == {"north": 3}
    assert plan.files == 1 and sum(d["files"] for d in plan.by_drive) == 1
    with pytest.raises(ValidationError):
        ReleaseScope(collections=["north"], query=RecordQuery(dataset="north"))
    with pytest.raises(ValidationError):
        ReleaseScope(records=[])


def test_its_records_read_back_into_a_new_project(ctx, study, tmp_path):
    made = _make(ctx)
    path = tmp_path / "r.zip"
    with ctx.release_svc.open_bundle(made.name) as (_, f):
        path.write_bytes(f.read())
    root = tmp_path / "restored"
    scaffold_project(root)
    other = build_local_context(load_config_at(root))
    try:
        result = other.bundle_svc.import_bundle(path)
        other.commit()
        assert result.records_added == 4 and result.files_added == 0
    finally:
        other.close()


def test_verify_checks_the_records_and_that_every_file_is_recorded(ctx, study):
    made = _make(ctx)
    good = ctx.release_svc.verify("v1")
    assert good.matches and good.bundle_intact and good.actual == made.content_hash
    assert good.files == 1 and good.files_not_here == 0

    # A cited file the inventory no longer has is a problem (nothing is read).
    ctx.file_svc._store.delete(study["photo"].sha256)
    ctx.commit()
    lost = ctx.release_svc.verify("v1")
    assert not lost.matches and lost.files_not_here == 1


def test_verify_finds_a_tampered_bundle(ctx, study):
    made = _make(ctx)
    path = ctx.file_svc.object_path(made.bundle_sha256)
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(path) as old, zipfile.ZipFile(rebuilt, "w") as new:
        for name in old.namelist():
            data = old.read(name)
            if name == "records.jsonl":
                data = data.replace(b'"depth":2.0', b'"depth":3.0')
            new.writestr(name, data)
    path.chmod(0o644)
    path.write_bytes(rebuilt.getvalue())
    bad = ctx.release_svc.verify("v1")
    assert not bad.matches and not bad.bundle_intact
    assert bad.actual != made.content_hash and bad.problems


def test_a_deep_verify_reads_every_file_back(ctx, study):
    _make(ctx)
    good = ctx.release_svc.verify("v1", deep=True)
    assert good.matches and good.files_read == 1 and not good.files_bad
    sha = study["photo"].sha256
    disk = ctx.file_svc.object_path(sha)
    disk.chmod(0o644)
    disk.write_bytes(b"rotted")
    bad = ctx.release_svc.verify("v1", deep=True)
    assert not bad.matches and bad.files_bad == [sha]


def test_citations(ctx, study):
    _make(
        ctx,
        licence="CC-BY-4.0",
        doi="10.1234/abcd",
        keywords=["seals", "acoustics"],
        authors=[
            {
                "name": "Ada Lovelace",
                "orcid": "https://orcid.org/0000-0002-1825-0097",
                "affiliation": "Analytical Society",
            }
        ],
    )
    text = ctx.release_svc.cite("v1")
    assert text.startswith("Ada Lovelace (") and "(Version v1) [Data set]." in text
    assert "https://doi.org/10.1234/abcd" in text and "sha256:" in text
    bib = ctx.release_svc.cite("v1", "bibtex")
    assert bib.startswith("@misc{Lovelace") and "keywords = {seals, acoustics}" in bib
    cff = ctx.release_svc.cite("v1", "cff")
    assert 'family-names: "Lovelace"' in cff
    assert 'orcid: "https://orcid.org/0000-0002-1825-0097"' in cff
    assert 'affiliation: "Analytical Society"' in cff and '- "seals"' in cff
    preview = ctx.release_svc.preview(
        {"title": "Draft", "authors": [{"name": "Bo Li"}]}, "v2", "text"
    )
    assert preview.startswith("Bo Li (") and "Draft (Version v2)" in preview
    with pytest.raises(ValidationError):
        ctx.release_svc.cite("v1", "rtf")


def test_names_metadata_and_immutability(ctx, study):
    _make(ctx)
    with pytest.raises(AlreadyExistsError):
        _make(ctx)
    for bad in ("", "has space", "-v1", "x" * 65):
        with pytest.raises(ValidationError):
            ctx.release_svc.create(bad, "t")
    with pytest.raises(ValidationError):
        ctx.release_svc.create("v9", "  ")
    with pytest.raises(ValidationError):
        ctx.release_svc.create("v9", "t", doi="not a doi")
    with pytest.raises(ValidationError, match="ORCID"):
        ctx.release_svc.create("v9", "t", authors=[{"name": "A", "orcid": "123"}])
    with pytest.raises(ValidationError):
        ctx.release_svc.correct("v1", content_hash="sha256:00")


def test_corrections_withdrawal_and_yank_are_in_history(ctx, study):
    made = _make(ctx)
    fixed = ctx.release_svc.correct("v1", title="Seal survey 2026", doi="10.5555/x")
    ctx.commit()
    assert fixed.title == "Seal survey 2026" and fixed.content_hash == made.content_hash
    gone = ctx.release_svc.withdraw("v1", "Calibration error in north")
    ctx.commit()
    assert gone.withdrawn_reason == "Calibration error in north"
    with pytest.raises(ValidationError):
        ctx.release_svc.withdraw("v1", "again")
    # Withdrawn releases keep their data, and still verify.
    assert ctx.release_svc.verify("v1").matches
    yanked = ctx.release_svc.yank("v1", "Consent withdrawn")
    ctx.commit()
    assert yanked.yanked_at and yanked.yanked_reason == "Consent withdrawn"
    assert yanked.withdrawn_reason == "Calibration error in north"
    with pytest.raises(ValidationError):
        ctx.release_svc.yank("v1", "again")
    with pytest.raises(ValidationError):
        ctx.release_svc.correct("v1", title="x")
    # The tombstone still answers a citation; the data is gone from it.
    assert "sha256:" in ctx.release_svc.cite("v1")
    assert not ctx.release_svc.verify("v1").matches
    entries = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_type == "release")
        .order_by(AuditLog.local_seq)
        .all()
    )
    assert [e.action for e in entries] == ["create", "update", "update", "update"]
    changes = ctx.history_svc.get(str(entries[1].id)).changes
    assert {c["field"] for c in changes} >= {"title", "doi"}


def test_clean_up_keeps_a_release_files_and_frees_them_after_a_yank(ctx, study):
    made = _make(ctx)
    photo = study["photo"].sha256
    # The record lets the photo go: only the release keeps it now.
    ctx.record_svc.update(str(study["a"].id), {"photo": None})
    ctx.commit()
    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert {photo, made.bundle_sha256}.isdisjoint(o.sha256 for o in report.deleted)
    assert ctx.release_svc.verify("v1").matches

    plan = ctx.release_svc.plan_yank("v1")
    assert (plan.files, plan.unused_files, plan.kept_files) == (2, 2, 0)
    assert plan.unused_bytes == len(b"a photo") + made.bundle_size
    assert set(_owned(ctx, made)) == {photo, made.bundle_sha256}  # nothing changed

    ctx.release_svc.yank("v1", "Not ours to share")
    ctx.commit()
    assert _owned(ctx, made) == {}
    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert {photo, made.bundle_sha256} <= {o.sha256 for o in report.deleted}


def test_a_yank_counts_files_others_still_use_as_kept(ctx, study):
    _make(ctx)
    plan = ctx.release_svc.plan_yank("v1")
    # The photo is still the record's; only the bundle would go.
    assert (plan.unused_files, plan.kept_files) == (1, 1)


def test_a_permanent_delete_says_which_release_keeps_the_files(ctx, study):
    _make(ctx)
    a = study["a"]
    ctx.record_svc.delete(str(a.id))
    ctx.commit()
    ids = ctx.record_svc.purge_set(str(a.id))
    assert len(ids) == 3
    assert ctx.release_svc.kept_for(ids) == {"v1": 1}


# -- moving files -------------------------------------------------------------


def _drives(ctx: AppContext, tmp_path: Path, *names: str) -> None:
    for name in names:
        path = tmp_path / "mnt" / name
        path.mkdir(parents=True)
        ctx.store_svc.add_volume(name, str(path))
    ctx.store_svc.set_queue([names[0]])
    ctx.commit()


def _move(ctx: AppContext, spec: TransferSpec) -> None:
    run_transfer(
        ctx.file_svc._store,
        LocalFileReferenceRepository(ctx._session),
        spec,
        progress=lambda _: None,
        commit=ctx.commit,
    )


def _consolidate(ctx: AppContext, collection: str, target: str) -> None:
    cid = str(ctx.dataset_svc.get(collection).id)
    _move(
        ctx,
        TransferSpec(kind=KIND_CONSOLIDATE, collection_ids=[cid], targets=[target]),
    )


def _on(ctx: AppContext, sha: str) -> list[str]:
    return sorted(v for v, _ in ctx.file_svc._store.copies([sha]).get(sha, []))


def _one_photo(ctx: AppContext, *collections: str):
    ctx.schema_svc.create("site")
    ctx.schema_svc.add_field("site", "photo", "file")
    photo = ctx.file_svc.store_bytes(b"photo", "p.jpg")
    made = []
    for c in collections:
        ctx.dataset_svc.create(c)
        made.append(ctx.record_svc.add(c, "site", {"photo": photo.to_dict()}))
    ctx.commit()
    return photo, made


def test_a_release_pointer_moves_with_its_records(ctx, tmp_path):
    _drives(ctx, tmp_path, "a", "b")
    photo, _ = _one_photo(ctx, "north")
    made = _make(ctx)
    assert _owned(ctx, made)[photo.sha256] == "a"
    _consolidate(ctx, "north", "b")
    # Every record at the copy on a moved, so the release went with them and
    # the copy on a was freed (it didn't keep it behind by itself).
    assert _owned(ctx, made)[photo.sha256] == "b"
    assert _on(ctx, photo.sha256) == ["b"]


def test_a_release_pointer_stays_with_the_records_that_stay(ctx, tmp_path):
    _drives(ctx, tmp_path, "a", "b")
    photo, _ = _one_photo(ctx, "north", "south")
    made = _make(ctx)
    _consolidate(ctx, "north", "b")
    # South still points at the copy on a, so it stays, and the release too.
    assert _owned(ctx, made)[photo.sha256] == "a"
    assert _on(ctx, photo.sha256) == ["a", "b"]


def test_gathering_a_release_moves_only_its_own_pointers(ctx, tmp_path):
    _drives(ctx, tmp_path, "a", "b")
    photo, (rec,) = _one_photo(ctx, "north")
    made = _make(ctx)
    spec = ctx.release_svc.gather_spec("v1", "b")
    assert spec.shas == [photo.sha256] and spec.release_ids == [str(made.id)]
    _move(ctx, spec)
    assert _owned(ctx, made)[photo.sha256] == "b"
    # The record's copy stays where it was: copied for the release, not moved.
    assert ctx.file_svc._store.copies_used([rec.id])[(rec.id, photo.sha256)] == "a"
    assert _on(ctx, photo.sha256) == ["a", "b"]


# -- getting the data out -----------------------------------------------------


def test_the_files_come_out_as_any_export_with_a_bagit_manifest(ctx, study):
    _make(ctx)
    plan = ctx.release_svc.file_plan("v1")
    assert [i.path for i in plan.items] == ["A/p.jpg"]
    assert plan.complete
    with ctx.release_svc.file_access("v1") as (access, selection):
        result = access.export_managed(selection, "release-v1", "copy")
    dest = Path(result.dest)
    ctx.release_svc.write_bag("v1", dest, plan)
    assert (dest / "A" / "p.jpg").read_bytes() == b"a photo"
    manifest = (dest / BAG_MANIFEST).read_text().splitlines()
    assert manifest == [f"{study['photo'].sha256}  A/p.jpg"]
    assert json.loads((dest / rules.RELEASE_JSON).read_text())["name"] == "v1"
    assert (dest / rules.CITATION_CFF).exists()


def test_the_files_are_laid_out_as_frozen_even_after_edits(ctx, study):
    _make(ctx)
    ctx.record_svc.update(str(study["a"].id), {"name": "Renamed"})
    ctx.commit()
    assert [i.path for i in ctx.release_svc.file_plan("v1").items] == ["A/p.jpg"]


def test_changes_since_a_release(ctx, study):
    _make(ctx)
    assert ctx.release_svc.changes_since("v1").added == 0
    a = study["a"]
    ctx.record_svc.update(str(a.id), {"name": "A2"})
    ctx.record_svc.add("south", "site", {"name": "C"})
    b = ctx.record_svc.find("south", "site", filters=["name=B"])[0]
    ctx.record_svc.delete(str(b.id))
    temp = ctx.record_svc.add("south", "site", {"name": "T"})
    ctx.record_svc.delete(str(temp.id))  # made and deleted since: nothing
    ctx.schema_svc.add_field("site", "notes", "string")
    ctx.commit()

    since = ctx.release_svc.changes_since("v1")
    assert since.comparable and since.by == "local"
    assert (since.added, since.changed, since.deleted) == (1, 1, 1)
    by_name = {c.collection: c for c in since.collections}
    assert (by_name["north"].changed, by_name["south"].added) == (1, 1)
    assert by_name["south"].deleted == 1
    assert since.structure.get("field") == 1 and "release" not in since.structure


@contextmanager
def _statements(ctx: AppContext):
    seen: list[str] = []

    def record(conn, cursor, statement, *_):
        seen.append(statement)

    engine = ctx._session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_changes_since_costs_the_same_however_much_changed(ctx, study):
    _make(ctx)

    def cost() -> int:
        ctx.release_svc.changes_since("v1")  # warm
        with _statements(ctx) as seen:
            ctx.release_svc.changes_since("v1")
        return len(seen)

    few = cost()
    for i in range(60):
        ctx.record_svc.add("north" if i % 2 else "south", "site", {"name": f"s{i}"})
    ctx.commit()
    assert cost() == few


def test_owning_the_files_costs_the_same_however_many_there_are(ctx, study):
    """The files are owned in one INSERT ... SELECT: making a release of a
    collection asks the same few questions of file_references whether its
    records cite one file or a hundred."""

    def cost(name: str) -> int:
        with _statements(ctx) as seen:
            _make(ctx, name, scope=ReleaseScope(collections=["south"]))
        return len([s for s in seen if "file_references" in s])

    few = cost("few")
    for i in range(100):
        ref = ctx.file_svc.store_bytes(f"photo {i}".encode(), f"p{i}.jpg")
        ctx.record_svc.add("south", "site", {"name": f"s{i}", "photo": ref.to_dict()})
    ctx.commit()
    assert cost("many") == few


def test_a_synced_copy_with_unsent_changes_must_sync_first(ctx, study):
    ctx.release_svc.position = lambda: (7, 2)
    with pytest.raises(ValidationError, match="sync first"):
        ctx.release_svc.create("v1", "t")
    ctx.release_svc.position = lambda: (7, 0)
    made = _make(ctx)
    assert made.feed_seq == 7
    assert ctx.release_svc.changes_since("v1").by == "feed"


def test_who_may_make_withdraw_and_yank_releases(tmp_path: Path):
    root = tmp_path / "study"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("sample")
    owner.dataset_svc.create("mine")
    owner.record_svc.add("mine", "sample", {})
    owner.release_svc.create("v1", "t")
    owner.commit()

    def as_(perms: Permissions) -> AppContext:
        return build_context(
            Project(
                config=load_config_at(root),
                config_store=FileConfigStore(root),
                actor="someone",
                permissions=perms,
            )
        )

    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS))
    try:
        assert [r.name for r in writer.release_svc.list_all()] == ["v1"]
        assert writer.release_svc.verify("v1").matches
        for attempt in (
            lambda: writer.release_svc.create("v2", "t"),
            lambda: writer.release_svc.withdraw("v1", "no"),
            lambda: writer.release_svc.yank("v1", "no"),
            lambda: writer.release_svc.correct("v1", title="x"),
        ):
            with pytest.raises(NotAllowedError):
                attempt()
    finally:
        writer.close()
        owner.close()
