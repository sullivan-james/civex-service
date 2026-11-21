"""Releases (`civex.domain.release`): making one from the bundle exporter, the
content hash (the same for the same data, whatever the zip's bytes), verify,
citations, corrections and withdrawal in history, what changed since, who may,
and that GC keeps a release's bundle."""

from __future__ import annotations

import io
import json
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event

from civex.config import FileConfigStore, load_config_at
from civex.context import AppContext, build_context, build_local_context
from civex.db.models import AuditLog
from civex.domain import permissions as p
from civex.domain import release as rules
from civex.domain.exceptions import (
    AlreadyExistsError,
    NotAllowedError,
    ValidationError,
)
from civex.domain.permissions import Permissions
from civex.domain.query import RecordQuery
from civex.project import Project, scaffold_project
from civex.services.release_service import ReleaseScope


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
        name, kw.pop("title", "Seal survey"), authors=["Ada Lovelace"], **kw
    )
    ctx.commit()
    return made


def _members(ctx: AppContext, release) -> dict[str, bytes]:
    with ctx.release_svc.open_bundle(release.name) as (_, f):
        with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
            return {n: zf.read(n) for n in zf.namelist()}


def test_a_release_is_a_bundle_kept_in_the_store_with_its_manifest(ctx, study):
    made = _make(ctx, licence="CC-BY-4.0", doi="https://doi.org/10.1234/abcd")
    assert made.content_hash.startswith(rules.HASH_PREFIX)
    assert made.doi == "10.1234/abcd"
    assert made.counts["records"] == 4
    assert made.counts["files_carried"] == 1
    assert made.scope == {}
    assert made.local_seq and made.feed_seq is None
    assert ctx.file_svc.exists(made.bundle_sha256)
    members = _members(ctx, made)
    assert {
        "bundle.json",
        "records.jsonl",
        rules.RELEASE_JSON,
        rules.CITATION_CFF,
    } <= set(members)
    assert f"files/{study['photo'].sha256}" in members
    manifest = json.loads(members[rules.RELEASE_JSON])
    assert manifest["content_hash"] == made.content_hash
    assert 'title: "Seal survey"' in members[rules.CITATION_CFF].decode()
    # Where a file is stored here is never frozen into the bundle.
    assert b"location" not in members["records.jsonl"]
    assert ctx.release_svc.get("v1").id == made.id
    assert [r.name for r in ctx.release_svc.list_all()] == ["v1"]


def test_the_same_data_hashes_the_same_however_often_it_is_frozen(ctx, study):
    first = _make(ctx, "v1")
    second = _make(ctx, "v2", title="Another title")
    assert first.content_hash == second.content_hash
    # The zips differ (they carry the time they were written, and the name).
    assert first.bundle_sha256 != second.bundle_sha256
    ctx.record_svc.add("south", "site", {"name": "C"})
    ctx.commit()
    assert _make(ctx, "v3").content_hash != first.content_hash


def test_scope_collections_or_a_query(ctx, study):
    north = _make(ctx, "north", scope=ReleaseScope(collections=["north"]))
    assert north.counts["records"] == 3 and north.scope == {"collections": ["north"]}
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
    assert deep.counts["records"] == 2
    assert deep.scope["query"]["schema"] == "sample"
    plan = ctx.release_svc.plan(
        ReleaseScope(collections=["south"]), include_files=False
    )
    assert plan.records == 1 and not plan.include_files
    with pytest.raises(ValidationError):
        ReleaseScope(collections=["north"], query=RecordQuery(dataset="north"))


def test_a_release_reads_back_into_a_new_project(ctx, study, tmp_path):
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
        assert result.records_added == 4 and result.files_added == 1
    finally:
        other.close()


def test_verify_says_whether_the_bundle_still_holds_what_it_was_made_with(ctx, study):
    made = _make(ctx)
    good = ctx.release_svc.verify("v1")
    assert good.matches and good.bundle_intact and good.actual == made.content_hash

    # Tamper with the stored bundle: change one record's value.
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


def test_citations(ctx, study):
    _make(ctx, licence="CC-BY-4.0", doi="10.1234/abcd")
    text = ctx.release_svc.cite("v1")
    assert text.startswith("Ada Lovelace (") and "(Version v1) [Data set]." in text
    assert "https://doi.org/10.1234/abcd" in text and "sha256:" in text
    bib = ctx.release_svc.cite("v1", "bibtex")
    assert bib.startswith("@misc{Lovelace") and "doi = {10.1234/abcd}" in bib
    cff = ctx.release_svc.cite("v1", "cff")
    assert 'family-names: "Lovelace"' in cff and 'given-names: "Ada"' in cff
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
    with pytest.raises(ValidationError):
        ctx.release_svc.correct("v1", content_hash="sha256:00")


def test_corrections_and_withdrawal_are_in_history(ctx, study):
    made = _make(ctx)
    fixed = ctx.release_svc.correct("v1", title="Seal survey 2026", doi="10.5555/x")
    ctx.commit()
    assert fixed.title == "Seal survey 2026" and fixed.content_hash == made.content_hash
    gone = ctx.release_svc.withdraw("v1", "Calibration error in north")
    ctx.commit()
    assert gone.withdrawn_at and gone.withdrawn_reason == "Calibration error in north"
    with pytest.raises(ValidationError):
        ctx.release_svc.withdraw("v1", "again")
    with pytest.raises(ValidationError):
        ctx.release_svc.withdraw("v1", "")
    entries = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_type == "release")
        .order_by(AuditLog.local_seq)
        .all()
    )
    assert [e.action for e in entries] == ["create", "update", "update"]
    changes = ctx.history_svc.get(str(entries[1].id)).changes
    assert {c["field"] for c in changes} >= {"title", "doi"}
    # Withdrawn releases still verify: the bundle is kept.
    assert ctx.release_svc.verify("v1").matches


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


def test_a_synced_copy_with_unsent_changes_must_sync_first(ctx, study):
    ctx.release_svc.position = lambda: (7, 2)
    with pytest.raises(ValidationError, match="sync first"):
        ctx.release_svc.create("v1", "t")
    ctx.release_svc.position = lambda: (7, 0)
    made = _make(ctx)
    assert made.feed_seq == 7
    assert ctx.release_svc.changes_since("v1").by == "feed"


def test_garbage_collection_keeps_a_release_bundle(ctx, study):
    made = _make(ctx)
    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert made.bundle_sha256 not in {o.sha256 for o in report.deleted}
    assert ctx.release_svc.verify("v1").matches


def test_who_may_make_and_withdraw_releases(tmp_path: Path):
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
        with pytest.raises(NotAllowedError):
            writer.release_svc.create("v2", "t")
        with pytest.raises(NotAllowedError):
            writer.release_svc.withdraw("v1", "no")
        with pytest.raises(NotAllowedError):
            writer.release_svc.correct("v1", title="x")
    finally:
        writer.close()
        owner.close()
