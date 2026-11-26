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


def test_chosen_records_come_with_what_is_inside_them(ctx, study):
    a = study["a"]
    whole = _make(ctx, "whole", scope=ReleaseScope(records=[str(a.id)], below=True))
    # The site and its two samples.
    assert whole.counts["records"] == 3 and whole.scope["below"] is True
    # Nothing has changed since: the samples are part of what it covers.
    now = ctx.release_svc.compare("whole")
    assert (now.added, now.changed, now.removed) == (0, 0, 0)
    # A sample added inside afterwards is new to it.
    ctx.record_svc.add("north", "sample", {"depth": 9.0}, parent_record_id=str(a.id))
    ctx.commit()
    assert ctx.release_svc.compare("whole").added == 1
    # Without it (as releases made before this were), only the record chosen.
    bare = _make(ctx, "bare", scope=ReleaseScope(records=[str(a.id)]))
    assert bare.counts["records"] == 1 and "below" not in bare.scope
    assert ctx.release_svc.compare("bare").added == 0


def test_code_is_left_out_of_a_release_unless_asked_for(ctx, study, project_dir):
    civex_dir = project_dir / "_civex"
    (civex_dir / "workflows").mkdir(exist_ok=True)
    (civex_dir / "plugins").mkdir(exist_ok=True)
    (civex_dir / "workflows" / "tidy.yaml").write_text("name: tidy\nsteps: []\n")
    (civex_dir / "plugins" / "mine.py").write_text("class Plugin: ...\n")

    data = _make(ctx, "data")
    assert (data.counts["workflows"], data.counts["plugins"]) == (0, 0)
    assert not [n for n in _members(ctx, data) if n.endswith((".yaml", ".py"))]
    assert ctx.release_svc.plan().workflows == 0

    code = _make(ctx, "code", include_workflows=True)
    assert (code.counts["workflows"], code.counts["plugins"]) == (1, 1)
    assert [n for n in _members(ctx, code) if n.endswith(".py")]


def test_a_value_left_under_a_field_that_no_longer_exists_is_not_in_the_way(ctx, study):
    """A record can still hold a value under the id of a field that is gone
    for good. It is not a field the record has: reads leave it out, and a
    release of the record is made and checks out."""
    from sqlalchemy.orm.attributes import flag_modified

    from civex.db.models import Record

    row = ctx._session.get(Record, study["a"].id)
    row.data = {
        **row.data,
        # The id of a field that is gone for good, and a name kept from
        # before values were stored by id, whose field has gone too.
        "c7a87f0d-e9e5-4d42-b298-354addb754e5": "left behind",
        "recording": "also left behind",
    }
    flag_modified(row, "data")
    ctx.commit()

    assert set(ctx.record_svc.get(str(study["a"].id)).data) == {"name", "photo"}
    made = _make(ctx)
    assert made.counts["records"] == 4
    assert ctx.release_svc.verify("v1").matches
    now = ctx.release_svc.compare("v1")
    assert (now.added, now.changed, now.removed) == (0, 0, 0)


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
    # The content hash is over records.hashes, which the edit didn't touch;
    # the lines no longer match it, and the zip isn't what was kept.
    assert any("records.hashes does not match" in p for p in bad.problems)


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


def _counts(c) -> tuple[int, int, int]:
    return c.added, c.changed, c.removed


def test_changing_a_kinds_charts_is_a_change_to_the_structure(ctx, study):
    _make(ctx)
    ctx.schema_svc.set_charts(
        "sample", [{"id": "a", "group_by": ["depth:5"], "measures": ["count"]}]
    )
    ctx.commit()
    now = ctx.release_svc.compare("v1")
    # The kind changed; no record did.
    assert _counts(now) == (0, 0, 0)
    assert now.structure == [
        {
            "kind": "schema",
            "change": "changed",
            "name": "sample",
            "schema": None,
            "what": ["charts"],
        }
    ]


def test_a_release_made_a_moment_ago_is_the_same_as_the_data(ctx, study):
    _make(ctx)
    now = ctx.release_svc.compare("v1")
    assert (now.records, now.unchanged) == (4, 4)
    assert _counts(now) == (0, 0, 0) and now.structure == []


def test_added_changed_and_removed_are_disjoint(ctx, study):
    _make(ctx)
    a = study["a"]
    ctx.record_svc.patch(str(a.id), {"name": "A2"})  # changed
    ctx.record_svc.add("south", "site", {"name": "C"})  # added
    b = ctx.record_svc.find("south", "site", filters=["name=B"])[0]
    ctx.record_svc.delete(str(b.id))  # removed (deleted)
    sample = ctx.record_svc.find("north", "sample", filters=["depth=1.0"])[0]
    ctx.record_svc.delete(str(sample.id))
    ctx.record_svc.purge(str(sample.id))  # removed (purged)
    temp = ctx.record_svc.add("south", "site", {"name": "T"})
    ctx.record_svc.delete(str(temp.id))  # made and deleted since: nothing
    ctx.commit()
    now = ctx.release_svc.compare("v1")
    assert _counts(now) == (1, 1, 2) and now.unchanged == 1
    by = {c.collection: _counts(c) for c in now.collections}
    assert by == {"north": (0, 1, 1), "south": (1, 0, 1)}
    total, items = ctx.release_svc.compared_records("v1", "removed")
    assert total == 2 and {i["name"] for i in items} == {"B", "1.0"}
    assert all(not i["live"] for i in items)
    _, (changed,) = ctx.release_svc.compared_records("v1", "changed")
    assert changed["id"] == str(a.id) and changed["name"] == "A2"
    (diff,) = ctx.release_svc.record_differences("v1", str(a.id))
    assert (diff.label, diff.before, diff.after) == ("name", "A", "A2")


def test_an_edit_undone_is_unchanged(ctx, study):
    _make(ctx)
    a = study["a"]
    ctx.record_svc.patch(str(a.id), {"name": "A2"})
    ctx.commit()
    assert ctx.release_svc.compare("v1").changed == 1
    ctx.record_svc.patch(str(a.id), {"name": "A"})
    ctx.commit()
    assert _counts(ctx.release_svc.compare("v1")) == (0, 0, 0)


def test_renaming_a_field_changes_no_record_but_is_a_structure_change(ctx, study):
    _make(ctx)
    ctx.schema_svc.update_field("site", "name", new_name="site_name", label="Site")
    ctx.schema_svc.add_field("site", "notes", "string")
    ctx.commit()
    now = ctx.release_svc.compare("v1")
    assert _counts(now) == (0, 0, 0)
    changes = {(c["kind"], c["name"], c["change"]) for c in now.structure}
    assert ("field", "site_name", "changed") in changes
    assert ("field", "notes", "added") in changes


def test_moving_a_record_out_of_scope_is_a_change(ctx, study):
    _make(ctx, scope=ReleaseScope(collections=["south"]))
    b = ctx.record_svc.find("south", "site", filters=["name=B"])[0]
    ctx.record_svc.move("north", ids=[str(b.id)])
    ctx.commit()
    now = ctx.release_svc.compare("v1")
    assert _counts(now) == (0, 1, 0)
    (moved,) = ctx.release_svc.record_differences("v1", str(b.id))
    assert (moved.label, moved.before, moved.after) == ("Collection", "south", "north")
    north = next(c.collection_id for c in now.collections)
    assert ctx.release_svc.compared_records("v1", "changed", collection=north)[0] == 1
    assert ctx.release_svc.compared_records("v1", "added", collection=north)[0] == 0


def test_a_picked_release_compares_only_what_its_pick_takes(ctx, study):
    a = study["a"]
    _make(ctx, scope=ReleaseScope(records=[str(a.id)]))
    ctx.record_svc.add("south", "site", {"name": "C"})  # outside the pick
    ctx.commit()
    now = ctx.release_svc.compare("v1")
    assert now.records >= 1 and _counts(now) == (0, 0, 0)


def test_history_does_not_change_the_answer(ctx, study):
    from civex.services import release_service

    _make(ctx)
    ctx.record_svc.update(str(study["a"].id), {"name": "A2"})
    ctx.record_svc.add("south", "site", {"name": "C"})
    ctx.commit()
    before = ctx.release_svc.compare("v1").to_dict()
    ctx._session.query(AuditLog).filter(AuditLog.entity_type == "record").delete()
    ctx.commit()
    release_service._COMPARED.clear()
    after = ctx.release_svc.compare("v1").to_dict()
    assert before | {"at": 0} == after | {"at": 0}


def test_a_comparison_is_kept_until_the_data_changes(ctx, study, monkeypatch):
    _make(ctx)
    first = ctx.release_svc.compare("v1")
    assert ctx.release_svc.compare("v1") is first
    ctx.record_svc.add("south", "site", {"name": "C"})
    ctx.commit()
    assert ctx.release_svc.compare("v1").added == 1


def test_a_large_release_is_compared_as_a_job(ctx, study, monkeypatch):
    from civex.services import release_service

    made = _make(ctx)
    assert not ctx.release_svc.in_background(made)
    monkeypatch.setattr(release_service, "COMPARE_INLINE_MAX", 2)
    assert ctx.release_svc.in_background(made)
    seen: list[tuple] = []

    class Watch:
        def phase(self, label, total=0, total_bytes=0):
            seen.append(("phase", label, total))

        def advance(self, done, total=None):
            seen.append(("advance", done))

    ctx.release_svc.compare("v1", Watch())  # type: ignore[arg-type]
    assert seen[0] == ("phase", "Comparing 4 records", 4)
    assert seen[-1] == ("advance", 4)


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


def test_comparing_costs_the_same_however_much_changed(ctx, study):
    from civex.services import release_service

    _make(ctx)

    def cost() -> int:
        release_service._COMPARED.clear()
        ctx.release_svc.compare("v1")  # warm
        release_service._COMPARED.clear()
        with _statements(ctx) as seen:
            ctx.release_svc.compare("v1")
        return len(seen)

    few = cost()
    for i in range(60):
        ctx.record_svc.add("north" if i % 2 else "south", "site", {"name": f"s{i}"})
    ctx.commit()
    assert cost() == few
    assert ctx.release_svc.compare("v1").added == 60


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


def test_scope_with_a_created_range_round_trips_and_selects(ctx, study):
    from datetime import datetime, timezone

    past = datetime(2000, 1, 1)  # naive means UTC
    scope = ReleaseScope(query=RecordQuery(schema="site", created_after=past))
    assert scope.query.created_after == past.replace(tzinfo=timezone.utc)
    assert ReleaseScope.from_dict(scope.to_dict()) == scope
    assert ctx.release_svc.plan(scope).records == 2
    none = ReleaseScope(query=RecordQuery(schema="site", created_before=past))
    assert ctx.release_svc.plan(none).records == 0
    made = _make(ctx, "recent", scope=scope)
    assert made.counts["records"] == 2
    assert made.scope["query"]["created_after"].startswith("2000-01-01")


def test_write_copy_reports_bytes_written(ctx: AppContext, study, tmp_path: Path):
    release = _make(ctx)
    seen: list[tuple[int, int]] = []
    out = tmp_path / "copy.zip"
    ctx.release_svc.write_copy(
        release.name, out, on_progress=lambda d, t: seen.append((d, t))
    )
    assert seen and seen[-1] == (out.stat().st_size, release.bundle_size)
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_a_held_back_release_can_be_discarded_and_its_name_reused(ctx, study):
    held = _make(ctx, "v1", publish=False)
    assert held.published_at is None
    assert _owned(ctx, held)
    with pytest.raises(ValidationError):
        ctx.release_svc.cite("v1")
    with pytest.raises(ValidationError):
        ctx.release_svc.full_bundle("v1")
    ctx.release_svc.discard("v1")
    ctx.commit()
    assert ctx.release_svc.list_all() == []
    assert not _owned(ctx, held)
    entry = ctx._session.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == "release", AuditLog.action == "delete"
        )
    ).one()
    assert str(entry.entity_id) == str(held.id)
    again = _make(ctx, "v1")
    assert again.published_at is not None and again.id != held.id


def test_a_published_release_cannot_be_discarded(ctx, study):
    from civex.domain.exceptions import ReleasePublishedError

    _make(ctx, "v1")
    _make(ctx, "v2", publish=False)
    ctx.release_svc.publish("v2")
    ctx.commit()
    for name in ("v1", "v2"):
        with pytest.raises(ReleasePublishedError):
            ctx.release_svc.discard(name)
    ctx.release_svc.yank("v1", "gone")
    ctx.commit()
    with pytest.raises(ReleasePublishedError):  # yanked after publishing
        ctx.release_svc.discard("v1")
    assert {r.name for r in ctx.release_svc.list_all()} == {"v1", "v2"}


def test_publishing_after_a_discard_or_twice_fails_cleanly(ctx, study):
    _make(ctx, "v1", publish=False)
    ctx.release_svc.publish("v1")
    ctx.commit()
    with pytest.raises(ValidationError):
        ctx.release_svc.publish("v1")
    from civex.domain.exceptions import NotFoundError

    _make(ctx, "v2", publish=False)
    ctx.release_svc.discard("v2")
    ctx.commit()
    with pytest.raises(NotFoundError):
        ctx.release_svc.publish("v2")


def test_publish_and_discard_race_is_decided_by_one_conditional_write(ctx, study):
    """Each is a single conditional statement, so whichever runs second finds
    nothing to do (no row lock needed, real SQLite)."""
    from datetime import datetime, timezone

    repo = ctx.release_svc._repo
    now = datetime.now(timezone.utc)
    a = _make(ctx, "v1", publish=False)
    assert repo.mark_published(a.id, now) is True
    assert repo.delete_held_back(a.id) is False  # discard lost
    assert repo.get(a.id) is not None
    assert repo.mark_published(a.id, now) is False
    b = _make(ctx, "v2", publish=False)
    assert repo.delete_held_back(b.id) is True
    assert repo.mark_published(b.id, now) is False  # publish lost
    assert repo.delete_held_back(b.id) is False
    assert repo.get(b.id) is None


def test_a_held_back_release_cannot_be_withdrawn_or_yanked(ctx, study):
    from civex.domain.exceptions import ReleaseHeldBackError

    _make(ctx, "v1", publish=False)
    with pytest.raises(ReleaseHeldBackError):
        ctx.release_svc.yank("v1", "x")
    with pytest.raises(ReleaseHeldBackError):
        ctx.release_svc.withdraw("v1", "x")
    ctx.release_svc.discard("v1")


def test_a_held_back_release_gives_out_no_files_or_manifest(ctx, study, tmp_path):
    _make(ctx, "v1", publish=False)
    for attempt in (
        lambda: ctx.release_svc.file_plan("v1"),
        lambda: ctx.release_svc.gather_spec("v1", "x"),
        lambda: ctx.release_svc.write_bag("v1", tmp_path, None),  # type: ignore[arg-type]
    ):
        with pytest.raises(ValidationError):
            attempt()
    with pytest.raises(ValidationError):
        with ctx.release_svc.frozen("v1"):
            pass


def test_a_held_back_release_is_seen_only_by_who_may_make_releases(tmp_path: Path):
    root = tmp_path / "study"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("sample")
    owner.release_svc.create("held", "t", publish=False)
    owner.release_svc.create("live", "t")
    owner.commit()
    reader = build_context(
        Project(
            config=load_config_at(root),
            config_store=FileConfigStore(root),
            actor="someone",
            permissions=Permissions.of(p.READ),
        )
    )
    try:
        assert {r.name for r in owner.release_svc.list_all()} == {"held", "live"}
        assert [r.name for r in reader.release_svc.list_all()] == ["live"]
        assert reader.release_svc.get("live")
        from civex.domain.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            reader.release_svc.get("held")
    finally:
        reader.close()
        owner.close()


def test_who_may_discard_a_release(tmp_path: Path):
    root = tmp_path / "study"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("sample")
    owner.release_svc.create("v1", "t", publish=False)
    owner.commit()
    writer = build_context(
        Project(
            config=load_config_at(root),
            config_store=FileConfigStore(root),
            actor="someone",
            permissions=Permissions.of(p.READ, p.WRITE_RECORDS),
        )
    )
    try:
        with pytest.raises(NotAllowedError):
            writer.release_svc.discard("v1")
        with pytest.raises(NotAllowedError):
            writer.release_svc.publish("v1")
    finally:
        writer.close()
        owner.close()
