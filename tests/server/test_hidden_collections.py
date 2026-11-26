"""A collection a host does not let the caller read is not there: the data API
leaves it out of every list, count, search and summary, answers 404 (never 403)
for anything of it asked for directly, and refuses writes that would touch it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.context import build_local_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.project import Project, scaffold_project
from civex.domain.features import LOCAL_FEATURES, RELEASES
from civex.server.app import create_app

# Releases are a host's feature: these tests are about one that offers them.
WITH_RELEASES = LOCAL_FEATURES | {RELEASES}
SECRET = "TOPSECRET"


class World:
    """One project, two collections: `open` (anyone) and `vault` (hidden from
    the people the tests call `outsider`), reached by client headers."""

    def __init__(self, root: Path) -> None:
        self.root = root
        owner = build_local_context(load_config_at(root))
        owner.schema_svc.create("sample")
        owner.schema_svc.add_field("sample", "label", "string")
        owner.schema_svc.add_field("sample", "scan", "file")
        owner.schema_svc.add_field("sample", "weight", "float")
        self.open = owner.dataset_svc.create("open")
        self.vault = owner.dataset_svc.create(f"{SECRET.lower()}-vault")
        self.shared = owner.dataset_svc.create("shared", scope="global")
        self.hidden_global = owner.dataset_svc.create("hidden-global", scope="global")
        blob = owner.file_svc.store_bytes(f"{SECRET} bytes".encode(), "vault.bin")
        self.sha = blob.sha256
        self.visible = [
            owner.record_svc.add(
                "open", "sample", {"label": f"visible {i}", "weight": i}
            )
            for i in range(2)
        ]
        self.hidden = [
            owner.record_svc.add(
                f"{SECRET.lower()}-vault",
                "sample",
                {
                    "label": f"{SECRET} {i}",
                    "weight": 100 + i,
                    "scan": blob.to_dict(),
                },
            )
            for i in range(3)
        ]
        self.hidden_in_global = owner.record_svc.add(
            "hidden-global", "sample", {"label": f"{SECRET} global"}
        )
        self.note = owner.note_svc.add(str(self.hidden[0].id), f"{SECRET} note")
        owner.note_svc.add(str(self.visible[0].id), "a plain note")
        owner.commit()
        owner.close()

    def project(self, perms: Permissions) -> Project:
        return Project(
            config=load_config_at(self.root),
            config_store=FileConfigStore(self.root),
            actor="Dr Example",
            permissions=perms,
            features=WITH_RELEASES,
        )


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "hosted"
    scaffold_project(root)
    return World(root)


def _client(world: World, perms: Permissions) -> TestClient:
    app = create_app(features=WITH_RELEASES)
    app.state.project_resolver = lambda request: world.project(perms)
    return TestClient(app, raise_server_exceptions=False)


def outsider_perms(world: World, *actions: str) -> Permissions:
    """Sees `open` and `shared` only, with `actions` there."""
    where = [world.open.id, world.shared.id]
    return Permissions.of(p.READ, *actions, read_collections=where, collections=where)


@pytest.fixture()
def owner(world: World) -> TestClient:
    return _client(world, Permissions.everything())


@pytest.fixture()
def outsider(world: World) -> TestClient:
    return _client(world, outsider_perms(world, p.WRITE_RECORDS, p.NOTES))


def _everywhere(value: Any) -> str:
    return str(value)


# -- lists, counts, search, summaries ------------------------------------------------


def test_the_owner_sees_everything(owner: TestClient, world: World):
    names = {d["name"] for d in owner.get("/api/collections").json()}
    assert f"{SECRET.lower()}-vault" in names
    assert (
        owner.get("/api/records/count", params={"schema": "sample"}).json()["count"]
        == 6
    )


def test_a_hidden_collection_is_absent_from_lists(outsider: TestClient, world: World):
    names = {d["name"] for d in outsider.get("/api/collections").json()}
    assert names == {"open", "shared"}
    listing = outsider.get("/api/records/all", params={"schema": "sample"})
    assert listing.status_code == 200
    assert SECRET not in listing.text
    assert len(listing.json()["items"]) == 2
    assert (
        outsider.get("/api/records/count", params={"schema": "sample"}).json()["count"]
        == 2
    )


def test_search_never_finds_a_hidden_record(outsider: TestClient):
    for url in (
        f"/api/records/search?q={SECRET}",
        f"/api/records?schema=sample&search={SECRET}",
        f"/api/schemas/sample/records?search={SECRET}",
        f"/api/records/all?schema=sample&search={SECRET}",
    ):
        answer = outsider.get(url)
        assert SECRET not in answer.text, url
        body = answer.json()
        items = body if isinstance(body, list) else body.get("items", [])
        assert items == [], url


def test_counts_summaries_and_charts_leave_it_out(outsider: TestClient, world: World):
    counts = outsider.get("/api/records/counts")
    assert counts.status_code == 200
    assert SECRET not in counts.text
    summary = outsider.post(
        "/api/records/summary",
        json={
            "schema_name": "sample",
            "group_by": ["label"],
            "measures": ["count", "sum:weight"],
        },
    )
    assert summary.status_code == 200, summary.text
    assert len(summary.json()["rows"]) == 2
    assert SECRET not in summary.text and "301" not in summary.text
    assert outsider.get("/api/analytics/records/counts").status_code in (200, 404)
    assert SECRET not in outsider.get("/api/analytics/records/counts").text


def test_an_export_leaves_it_out(outsider: TestClient):
    csv = outsider.get("/api/collections/open/export.csv", params={"schema": "sample"})
    assert SECRET not in csv.text
    gone = outsider.get(
        f"/api/collections/{SECRET.lower()}-vault/export.csv",
        params={"schema": "sample"},
    )
    assert gone.status_code == 404


# -- direct access is a 404 ----------------------------------------------------------


def test_a_hidden_record_is_a_404_never_a_403(outsider: TestClient, world: World):
    rid = str(world.hidden[0].id)
    for method, url in (
        ("get", f"/api/records/{rid}"),
        ("get", f"/api/records/{rid}/notes"),
        ("get", f"/api/records/{rid}/audit"),
        ("get", f"/api/records/{rid}/restore-plan"),
        ("get", f"/api/records/{rid}/files.zip"),
        ("get", f"/api/records/{rid}/referrers"),
        ("patch", f"/api/records/{rid}"),
        ("delete", f"/api/records/{rid}"),
    ):
        kwargs: dict[str, Any] = (
            {"json": {"data": {"label": "x"}}} if method == "patch" else {}
        )
        answer = getattr(outsider, method)(url, **kwargs)
        assert answer.status_code in (404, 405), (method, url, answer.status_code)
        assert SECRET not in answer.text, (method, url)


def test_a_hidden_collection_is_a_404(outsider: TestClient):
    name = f"{SECRET.lower()}-vault"
    for url in (
        f"/api/collections/{name}",
        f"/api/collections/{name}/record-counts",
        f"/api/collections/{name}/audit",
    ):
        assert outsider.get(url).status_code == 404, url


def test_a_hidden_note_is_a_404(outsider: TestClient, world: World):
    rid = str(world.hidden[0].id)
    assert (
        outsider.post(f"/api/records/{rid}/notes", json={"body": "hi"}).status_code
        == 404
    )
    assert (
        outsider.patch(f"/api/notes/{world.note.id}", json={"body": "x"}).status_code
        == 404
    )


def test_a_hidden_records_file_is_a_404(
    outsider: TestClient, owner: TestClient, world: World
):
    assert owner.get(f"/api/files/{world.sha}").status_code == 200
    assert outsider.get(f"/api/files/{world.sha}").status_code == 404
    assert outsider.get(f"/api/files/{world.sha}/info").status_code == 404


def test_history_and_audit_leave_it_out(outsider: TestClient):
    for url in ("/api/audit", "/api/audit/events", "/api/schemas/sample/audit"):
        answer = outsider.get(url)
        assert answer.status_code == 200, url
        assert SECRET not in answer.text, url


# -- writes -----------------------------------------------------------------------


def test_writes_that_would_touch_a_hidden_collection_are_refused(
    outsider: TestClient, world: World
):
    name = f"{SECRET.lower()}-vault"
    made = outsider.post(
        f"/api/collections/{name}/records",
        json={"schema_name": "sample", "data": {"label": "x"}},
    )
    assert made.status_code == 404, made.text
    # Moving a visible record into it
    plan = outsider.post(
        "/api/records/move",
        json={"ids": [str(world.visible[0].id)], "to": name},
    )
    assert plan.status_code in (404, 422), plan.text
    assert SECRET not in plan.text


def test_a_reference_to_a_hidden_record_cannot_be_made(world: World):
    owner = build_local_context(load_config_at(world.root))
    owner.schema_svc.add_field(
        "sample", "friend", "reference", restrictions={"schema": "sample"}
    )
    owner.commit()
    owner.close()
    client = _client(world, outsider_perms(world, p.WRITE_RECORDS))
    answer = client.post(
        "/api/collections/shared/records",
        json={
            "schema_name": "sample",
            "data": {"label": "x", "friend": str(world.hidden_in_global.id)},
        },
    )
    assert answer.status_code in (404, 422), answer.text


# -- the sweep: no route gives it away ---------------------------------------------


def _fill(path: str, world: World) -> tuple[str, bool]:
    """The path with every parameter given a value; whether one of them names
    something hidden (so a 200 would be a leak)."""
    vault = f"{SECRET.lower()}-vault"
    values = {
        "record_id": str(world.hidden[0].id),
        "note_id": str(world.note.id),
        "sha256": world.sha,
        "name_or_id": vault,
        "dataset_name": vault,
        "collection_name": vault,
        "collection": vault,
        "dataset": vault,
    }
    hidden = False
    for key, value in values.items():
        if "{" + key + "}" in path:
            path = path.replace("{" + key + "}", value)
            hidden = True
    if "{name}" in path:
        # a schema's name under /schemas, a collection's anywhere else
        if path.startswith("/api/collections/"):
            path = path.replace("{name}", vault)
            hidden = True
        else:
            path = path.replace("{name}", "sample")
    return path, hidden


_NEEDS_STATE = ("{",)


def test_no_get_route_gives_a_hidden_collection_away(
    outsider: TestClient, world: World
):
    app = outsider.app
    spec = app.openapi()  # type: ignore[attr-defined]
    seen = 0
    for path, methods in spec["paths"].items():
        if "get" not in methods:
            continue
        url, hidden = _fill(path, world)
        if any(t in url for t in _NEEDS_STATE):
            continue  # a parameter this test has no value for
        wanted = {
            p_["name"]
            for p_ in methods["get"].get("parameters", [])
            if p_["in"] == "query" and p_.get("required")
        }
        given = {
            "schema": "sample",
            "schema_name": "sample",
            "q": "probe",
            "search": "probe",
        }
        answer = outsider.get(url, params={k: given.get(k, "probe") for k in wanted})
        seen += 1
        assert SECRET not in answer.text, (url, answer.text[:300])
        if answer.status_code == 200:
            assert str(world.hidden[0].id) not in answer.text, url
        if hidden:
            assert answer.status_code != 200 or answer.headers.get(
                "content-length"
            ) in (None, "0"), (url, answer.status_code)
            if not url.startswith(
                "/api/releases"
            ):  # those are for whole-project readers
                assert answer.status_code != 403, url  # never says it is there
    assert seen > 40


def test_bulk_and_planning_routes_do_not_see_it(world: World):
    client = _client(
        world,
        outsider_perms(world, p.WRITE_RECORDS, p.DELETE, p.ADD_FILES, p.DELETE_FILES),
    )
    hidden = [str(r.id) for r in world.hidden]
    assert client.post("/api/records/labels", json={"ids": hidden}).json() == []
    for url, body in (
        ("/api/file-access/plan", {"ids": hidden}),
        ("/api/records/bulk-edit/plan", {"ids": hidden, "changes": {"label": "x"}}),
        ("/api/records/move/plan", {"ids": hidden, "to": "open"}),
        ("/api/records/restore-selected", {"ids": hidden}),
    ):
        answer = client.post(url, json=body)
        assert SECRET not in answer.text, url
        assert answer.status_code != 403, url
    count = client.post("/api/records/open-notes", json={"schema_name": "sample"})
    assert count.json()["notes"] == 1  # the visible record's, not the vault's
    # Nothing was deleted or changed by asking
    refused = client.post("/api/records/bulk-delete", json={"ids": hidden})
    assert refused.status_code in (200, 404)
    if refused.status_code == 200:
        assert refused.json()["deleted"] == 0
    changed = client.post(
        "/api/records/bulk-edit", json={"ids": hidden, "changes": {"label": "x"}}
    )
    assert SECRET not in changed.text
    owner = _client(world, Permissions.everything())
    for r in world.hidden:
        assert (
            owner.get(f"/api/records/{r.id}").json()["data"]["label"].startswith(SECRET)
        )


def test_a_reference_to_a_hidden_record_shows_no_label(world: World):
    owner = build_local_context(load_config_at(world.root))
    owner.schema_svc.add_field(
        "sample", "friend", "reference", restrictions={"schema": "sample"}
    )
    mine = owner.record_svc.add(
        "open",
        "sample",
        {"label": "points out", "friend": str(world.hidden_in_global.id)},
    )
    owner.commit()
    owner.close()
    client = _client(world, outsider_perms(world))
    answer = client.get(f"/api/records/{mine.id}")
    assert answer.status_code == 200
    assert SECRET not in answer.text
    assert str(world.hidden_in_global.id) in answer.text  # the raw id, as stored
    assert client.get(f"/api/records/{world.hidden_in_global.id}").status_code == 404


def test_a_dashboard_card_over_a_hidden_collection_says_so(world: World):
    owner = build_local_context(load_config_at(world.root))
    owner.dashboard_svc.add(
        chart={"group_by": ["label"], "measures": ["count"]},
        schema="sample",
        collection=world.vault.name,
    )
    owner.commit()
    owner.close()
    client = _client(world, outsider_perms(world))
    page = client.get("/api/dashboard")
    assert page.status_code == 200
    assert SECRET not in page.text
    assert "not available to you" in page.text
    # to someone who sees everything it is the same card, with its collection
    full = _client(world, Permissions.everything()).get("/api/dashboard")
    assert f"{SECRET.lower()}-vault" in full.text


def test_the_file_inventory_leaves_out_a_hidden_collections_files(
    outsider: TestClient, owner: TestClient, world: World
):
    seen = owner.post("/api/file-access/files", json={}).json()
    assert world.sha in str(seen) and sum(p["files"] for p in seen["summary"]) == 1
    assert {u["record_id"] for i in seen["items"] for u in i["uses"]} == {
        str(r.id) for r in world.hidden
    }

    hidden = outsider.post("/api/file-access/files", json={}).json()
    assert hidden["total"] == 0 and hidden["items"] == []
    assert sum(p["files"] for p in hidden["summary"]) == 0
    assert world.sha not in str(hidden) and SECRET not in str(hidden)
    for r in world.hidden:
        assert str(r.id) not in str(hidden)
    # Asking for the hidden collection by name finds nothing either.
    named = outsider.post(
        "/api/file-access/files", json={"collection": f"{SECRET.lower()}-vault"}
    )
    assert named.status_code == 404 or named.json()["total"] == 0


def test_a_limited_reader_lists_the_files_of_their_collections_only(
    outsider: TestClient, owner: TestClient, world: World
):
    """A file used by a visible and a hidden record is listed (no 500 from the
    use counts), with only the visible record citing it."""
    mine = owner.put(
        "/api/files/stream?filename=mine.bin",
        content=b"my own bytes",
        headers={"content-length": "12"},
    ).json()
    both = {"sha256": world.sha, "filename": "vault.bin", "size": len(SECRET) + 6}
    made = [
        owner.post(
            "/api/collections/open/records",
            json={"schema_name": "sample", "data": {"label": "a", "scan": ref}},
        )
        for ref in (mine, both)
    ]
    assert all(m.status_code == 201 for m in made), [m.text for m in made]
    visible_ids = {m.json()["id"] for m in made}

    answer = outsider.post("/api/file-access/files", json={})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert {i["sha256"] for i in body["items"]} == {mine["sha256"], world.sha}
    cited = {u["record_id"] for i in body["items"] for u in i["uses"]}
    assert cited == visible_ids
    assert sum(p["files"] for p in body["summary"]) == 2
    for r in world.hidden:
        assert str(r.id) not in str(body)


def test_two_scopes_through_one_engine_never_share_a_statement(
    outsider: TestClient, owner: TestClient, world: World
):
    """The read-scope rule is a lambda criterion: alternating callers with
    different scopes, on the same engine, each get their own rule."""
    for _ in range(3):
        full = owner.post("/api/file-access/files", json={}).json()
        limited = outsider.post("/api/file-access/files", json={}).json()
        assert world.sha in str(full) and world.sha not in str(limited)
        assert sum(p["files"] for p in full["summary"]) == 1
        assert sum(p["files"] for p in limited["summary"]) == 0
        counts = {
            who: c.get("/api/records/count", params={"schema": "sample"}).json()[
                "count"
            ]
            for who, c in (("owner", owner), ("outsider", outsider))
        }
        assert counts == {"owner": 6, "outsider": 2}
