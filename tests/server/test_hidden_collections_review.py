"""Regressions from the independent review of hidden collections: ways round
the rule that a collection the caller may not read is not there."""

from __future__ import annotations

import pytest

from civex.config import load_config_at
from civex.context import build_local_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from .test_hidden_collections import (  # noqa: F401
    SECRET,
    World,
    _client,
    outsider_perms,
    world,
)

NO_SUCH = "0" * 64


def _blob(sha: str, size: int = 15) -> dict:
    return {"sha256": sha, "filename": "x.bin", "size": size}


def _cite(client, sha: str, **extra):
    return client.post(
        "/api/collections/open/records",
        json={"schema_name": "sample", "data": {"label": "probe", "scan": _blob(sha)}},
        **extra,
    )


# -- 1: a hidden file cannot be had by citing its hash ------------------------------


def test_citing_a_hidden_files_hash_does_not_make_it_readable(world: World):
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS, p.NOTES, p.ADD_FILES))
    assert c.get(f"/api/files/{world.sha}").status_code == 404
    refused = _cite(c, world.sha)
    assert refused.status_code == 422
    assert refused.json()["detail"] == p.FILE_UNAVAILABLE
    assert c.get(f"/api/files/{world.sha}").status_code == 404
    assert c.get(f"/api/files/{world.sha}/info").status_code == 404
    # and the record was not made
    listing = c.get("/api/records/all", params={"schema": "sample"}).json()["items"]
    assert len(listing) == 2


def test_adding_the_citation_by_editing_is_refused_too(world: World):
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS, p.NOTES, p.ADD_FILES))
    record = c.post(
        "/api/collections/open/records",
        json={"schema_name": "sample", "data": {"label": "mine"}},
    ).json()
    r = c.patch(
        f"/api/records/{record['id']}", json={"data": {"scan": _blob(world.sha)}}
    )
    assert r.status_code == 422
    assert c.get(f"/api/files/{world.sha}").status_code == 404


def test_a_file_the_caller_uploaded_or_can_already_see_may_be_cited(world: World):
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS, p.NOTES, p.ADD_FILES))
    up = c.post("/api/files", files={"file": ("mine.bin", b"my own bytes")})
    assert up.status_code == 201
    ref = up.json()
    made = _cite(c, ref["sha256"])
    assert made.status_code == 201
    assert c.get(f"/api/files/{ref['sha256']}").status_code == 200
    # an unknown hash is refused in the same words as a hidden one, so the
    # answer says nothing about what the project holds (and citing a hash
    # before its bytes arrive cannot make them readable later)
    unknown = _cite(c, NO_SUCH)
    hidden = _cite(c, world.sha)
    assert unknown.status_code == hidden.status_code == 422
    assert unknown.json() == hidden.json()


def test_the_owner_may_cite_any_file(world: World):
    owner = _client(world, Permissions.everything())
    assert _cite(owner, world.sha).status_code == 201


# -- 2: a release is not in a restricted reader's history ---------------------------


def test_a_release_is_not_in_a_restricted_audit(world: World):
    o = build_local_context(load_config_at(world.root))
    rel = o.release_svc.create("v1", "Everything", authors=[{"name": "A"}])
    o.commit()
    o.close()
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS, p.ADD_FILES))
    body = c.get("/api/audit", params={"limit": 500}).text
    assert '"release"' not in body
    assert rel.bundle_sha256 not in body
    assert c.get("/api/releases").status_code == 403
    # the bundle cannot be fetched or cited either
    assert c.get(f"/api/files/{rel.bundle_sha256}").status_code == 404
    assert _cite(c, rel.bundle_sha256).status_code == 422
    owner = _client(world, Permissions.everything())
    assert '"release"' in owner.get("/api/audit", params={"limit": 500}).text


def test_an_audit_entry_of_an_unknown_type_is_hidden_from_a_restricted_reader(
    world: World,
):
    import sqlite3

    db = sqlite3.connect(world.root / "_civex" / "civex.db")
    db.execute(
        "INSERT INTO audit_log (id, action, entity_type, entity_id, timestamp, "
        "sync_state, apply_state) VALUES "
        "('00000000-0000-0000-0000-0000000000aa', 'create', 'mystery', "
        "'00000000-0000-0000-0000-0000000000bb', '2026-01-01', 'synced', 'applied')"
    )
    db.commit()
    db.close()
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS))
    assert "mystery" not in c.get("/api/audit", params={"limit": 500}).text
    owner = _client(world, Permissions.everything())
    assert "mystery" in owner.get("/api/audit", params={"limit": 500}).text


# -- 3: project-wide structure changes are for someone who sees everything --------


def _structural(world: World) -> object:
    where = [world.open.id, world.shared.id]
    return _client(
        world,
        Permissions.of(
            p.READ,
            p.WRITE_RECORDS,
            p.CHANGE_STRUCTURE,
            p.DELETE,
            read_collections=where,
        ),
    )


def test_deleting_or_purging_a_kind_is_refused_neutrally(world: World):
    s = _structural(world)
    for method, url in (
        ("DELETE", "/api/schemas/sample"),
        ("DELETE", "/api/schemas/sample/purge"),
        ("POST", "/api/schemas/sample/restore"),
    ):
        r = s.request(method, url)
        assert r.status_code == 403, (method, url, r.text)
        assert "everything" in r.json()["detail"]
    # nothing was touched, hidden records included
    o = build_local_context(load_config_at(world.root))
    try:
        assert all(o.record_svc.get(str(h.id)).deleted_at is None for h in world.hidden)
    finally:
        o.close()
    owner = _client(world, Permissions.everything())
    assert owner.delete("/api/schemas/sample").status_code in (200, 204)


# -- 4: a collection's name says nothing about hidden ones --------------------------


def test_a_hidden_collections_name_is_refused_like_any_taken_name(world: World):
    s = _structural(world)
    taken = s.post("/api/collections", json={"name": "open"})
    hidden = s.post("/api/collections", json={"name": f"{SECRET.lower()}-vault"})
    assert hidden.status_code == taken.status_code == 409
    assert s.post("/api/collections", json={"name": "fresh-name"}).status_code == 201
    # renaming onto one is the same
    r = s.patch("/api/collections/open", json={"rename": f"{SECRET.lower()}-vault"})
    assert r.status_code == 409
    assert (
        s.patch("/api/collections/open", json={"rename": "shared"}).status_code == 409
    )


# -- 17: the other doors -------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/db/summary"),
        ("GET", "/api/db/status"),
        ("GET", "/api/db/indexes"),
        ("GET", "/api/audit/storage"),
        ("POST", "/api/audit/storage/reclaim"),
        ("GET", "/api/jobs"),
        ("GET", "/api/jobs/count"),
        ("GET", "/api/analytics/jobs/status"),
        ("GET", "/api/analytics/jobs/by-trigger"),
        ("POST", "/api/workflows/anything/run"),
        ("POST", "/api/bundle/import"),
    ],
)
def test_whole_project_doors_are_for_someone_who_sees_everything(
    world: World, method: str, url: str
):
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS, p.CHANGE_STRUCTURE))
    assert c.request(method, url).status_code == 403
    owner = _client(world, Permissions.everything())
    assert owner.request(method, url).status_code != 403


def test_history_revert_and_restore_all_cannot_reach_a_hidden_collection(world: World):
    owner = _client(world, Permissions.everything())
    items = owner.get("/api/audit", params={"limit": 200}).json()["items"]
    hid = str(world.hidden[0].id)
    entry = next(i for i in items if i["entity_id"] == hid)["id"]
    c = _client(
        world, outsider_perms(world, p.WRITE_RECORDS, p.DELETE, p.CHANGE_STRUCTURE)
    )
    for method, url in (
        ("GET", f"/api/audit/{entry}"),
        ("GET", f"/api/audit/{entry}/revert"),
        ("POST", f"/api/audit/{entry}/revert"),
    ):
        assert c.request(method, url).status_code == 404, url
    owner.delete(f"/api/records/{hid}")
    plan = c.get("/api/audit/restore-all").json()
    assert plan["records"] == 0
    assert c.get(f"/api/records/{hid}/audit").status_code == 404


def test_exports_and_counts_hold_only_what_is_visible(world: World):
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS))
    csv = c.get("/api/collections/open/export.csv")
    assert SECRET not in csv.text
    assert c.get("/api/collections/topsecret-vault/export.csv").status_code == 404
    bundle = c.get("/api/bundle")
    assert bundle.status_code == 200
    assert SECRET.encode() not in bundle.content
    assert c.get("/api/bundle/plan").json()["records"] == 2
    assert c.get("/api/schemas/sample/delete-impact").json()["record_count"] == 2
    counts = c.get("/api/analytics/records/counts").json()["items"]
    assert [i["count"] for i in counts] == [2]


def test_note_history_follows_the_notes_record(world: World):
    c = _client(world, outsider_perms(world, p.WRITE_RECORDS, p.NOTES))
    body = c.get("/api/audit", params={"limit": 500}).text
    assert "a plain note" in body
    assert f"{SECRET} note" not in body
    owner = _client(world, Permissions.everything())
    assert f"{SECRET} note" in owner.get("/api/audit", params={"limit": 500}).text
