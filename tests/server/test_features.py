"""What a server does is said once (`domain.features`): a host that does less
leaves routers out and answers 501 on what is left, and the app reads the same
answer from `GET /api/status/features`."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.domain import features as f
from civex.project import Project, scaffold_project
from civex.server.app import api_routers, create_app

MACHINE_TOUCHING = {f.SERVER_PATH_EXPORT, f.PLUGIN_INSTALL, f.REMOTE_DIAL}
HOSTED = (
    f.LOCAL_FEATURES
    - {f.VOLUMES, f.TERMINAL, f.DESKTOP, f.LOCAL_WORKFLOWS}
    - MACHINE_TOUCHING
) | {f.RELEASES}


@pytest.fixture()
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A host with fewer features serving one project: the app is built with
    its feature set, and each request's project carries the same set."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "hosted"
    scaffold_project(root)
    app = create_app(features=HOSTED)
    app.state.project_resolver = lambda request: Project(
        config=load_config_at(root),
        config_store=FileConfigStore(root),
        actor="host",
        features=HOSTED,
    )
    return TestClient(app, raise_server_exceptions=False)


def test_the_local_app_offers_everything_a_machine_does(client: TestClient):
    answer = client.get("/api/status/features")
    assert answer.status_code == 200
    assert set(answer.json()["features"]) == f.LOCAL_FEATURES
    assert answer.json()["all"][f.VOLUMES]
    assert client.get("/api/store/volumes").status_code == 200


def test_a_narrower_host_says_what_it_does(hosted: TestClient):
    assert set(hosted.get("/api/status/features").json()["features"]) == HOSTED


def test_a_router_wholly_of_a_missing_feature_is_not_there(hosted: TestClient):
    assert hosted.get("/api/store/volumes").status_code == 404
    assert hosted.get("/api/workflows").status_code == 404
    assert hosted.get("/api/schemas").status_code == 200


def test_a_route_inside_a_shared_router_answers_501_in_plain_words(hosted: TestClient):
    answer = hosted.get("/api/settings/shortcut")
    assert answer.status_code == 501
    assert answer.json()["detail"] == f.unavailable_message(f.DESKTOP)
    assert hosted.get("/api/settings/identity").status_code == 200


def test_the_router_list_is_the_one_answer():
    """`api_routers` is what every host includes: with everything, every
    router; narrowed, exactly the routers whose feature is missing go."""
    every = f.LOCAL_FEATURES | {f.RELEASES}
    everything = {id(r) for r, _ in api_routers(every)}
    narrowed = {id(r) for r, _ in api_routers(HOSTED)}
    gone = {
        id(r) for r, feature in api_routers(every) if feature and feature not in HOSTED
    }
    assert narrowed == everything - gone
    assert all(feature is None or feature in f.FEATURES for _, feature in api_routers())


def test_a_drain_does_nothing_where_workflows_do_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from civex.context import build_context
    from civex.server.background import run_pending_jobs

    root = tmp_path / "hosted"
    scaffold_project(root)
    project = Project(
        config=load_config_at(root),
        config_store=FileConfigStore(root),
        actor="host",
        features=frozenset(),
    )
    opened: list[object] = []

    def make_context():
        ctx = build_context(project)
        opened.append(ctx)
        return ctx

    run_pending_jobs(make_context)
    assert len(opened) == 1  # it looked, saw the host runs nothing, and left


def test_me_says_who_and_what_they_may_do(client: TestClient, tmp_path: Path):
    """A project in a folder: the local user, everything. A host that knows a
    person and their role answers them, and the services refuse the rest."""
    from civex.domain.accounts import Account
    from civex.domain.permissions import READ, WRITE_RECORDS, Permissions

    me = client.get("/api/me").json()
    assert me["account"]["kind"] == "local" and me["account"]["manage_url"] is None
    assert me["permissions"]["actions"]["delete"] == ["project"]
    assert "delete" in me["permissions"]["all"]

    root = tmp_path / "hosted"
    scaffold_project(root)
    app = create_app()
    collection = {"id": None}

    def resolve(request):  # noqa: ANN001
        return Project(
            config=load_config_at(root),
            config_store=FileConfigStore(root),
            actor="Dr Example",
            permissions=Permissions.of(
                READ,
                WRITE_RECORDS,
                collections=[collection["id"]] if collection["id"] else [],
            )
            if collection["id"]
            else Permissions.everything(),
            account=Account(
                "Dr Example",
                "user",
                "https://hub.example/p/lab/study/settings",
                home_url="https://hub.example/",
                project="lab / study",
            ),
        )

    app.state.project_resolver = resolve
    hosted = TestClient(app, raise_server_exceptions=False)
    assert hosted.post("/api/schemas", json={"name": "sample"}).status_code == 201
    mine = hosted.post(
        "/api/collections", json={"name": "mine", "schemas": ["sample"]}
    ).json()
    theirs = hosted.post(
        "/api/collections", json={"name": "theirs", "schemas": ["sample"]}
    ).json()
    collection["id"] = mine["id"]  # from here on: a writer in `mine` only

    me = hosted.get("/api/me").json()
    assert me["account"] == {
        "name": "Dr Example",
        "kind": "user",
        "manage_url": "https://hub.example/p/lab/study/settings",
        "home_url": "https://hub.example/",
        "project": "lab / study",
    }
    assert me["permissions"]["actions"] == {
        "read": ["project"],
        "write_records": [f"collection:{mine['id']}"],
        # notes and shared views follow writing for a host that is silent on them
        "notes": [f"collection:{mine['id']}"],
        "views": [f"collection:{mine['id']}"],
    }
    body = {"schema_name": "sample", "data": {}}
    assert hosted.post("/api/collections/mine/records", json=body).status_code == 201
    refused = hosted.post("/api/collections/theirs/records", json=body)
    assert refused.status_code == 403
    assert refused.json()["detail"].startswith("You may not add, change")
    assert hosted.post("/api/schemas", json={"name": "other"}).status_code == 403
    assert hosted.delete(f"/api/collections/{theirs['name']}").status_code == 403
    assert hosted.get("/api/collections").status_code == 200


# -- the surfaces that touch the server's own machine -----------------------


def _bundle_with_code(raw: bytes) -> bytes:
    """`raw` (a bundle) with a plugin and a workflow definition added."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        dst.writestr("plugins/evil.py", "print('hi')\n")
        dst.writestr("workflows/flow.yaml", "name: flow\n")
    return out.getvalue()


def _post_bundle(c: TestClient, raw: bytes):
    return c.post("/api/bundle/import", files={"file": ("b.civex.zip", raw)})


def test_the_machine_touching_features_are_named_and_local(hosted: TestClient):
    assert MACHINE_TOUCHING <= f.LOCAL_FEATURES
    assert all(f.FEATURES[x] for x in MACHINE_TOUCHING)
    assert MACHINE_TOUCHING.isdisjoint(
        set(hosted.get("/api/status/features").json()["features"])
    )


def test_a_host_without_remote_dial_cannot_connect_out_but_can_administer(
    hosted: TestClient,
):
    answer = hosted.post(
        "/api/remote/connect",
        json={"url": "http://127.0.0.1:9", "invite": "civex_inv_x"},
    )
    assert answer.status_code == 501
    assert answer.json()["detail"] == f.unavailable_message(f.REMOTE_DIAL)
    assert hosted.post("/api/remote/sync").status_code == 501
    assert hosted.get("/api/remote/library").status_code == 501
    # The authority side (devices that connect to this server) is untouched.
    assert hosted.get("/api/remote/authority").status_code == 200


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/api/remote", None),
        ("patch", "/api/remote", {"paused": True}),
        ("get", "/api/remote/files", None),
        ("patch", "/api/remote/files/c", {"mode": "keep"}),
        ("post", "/api/remote/files/c/free-up", None),
        ("get", "/api/remote/conflicts", None),
        ("post", "/api/remote/conflicts/x/resolve", {"take": "theirs"}),
        ("post", "/api/remote/conflicts/resolve-many", {"ids": [], "take": "theirs"}),
        ("post", "/api/remote/conflicts/reopen", {"ids": []}),
    ],
)
def test_the_rest_of_the_dial_out_routes_answer_501_on_a_host(
    hosted: TestClient, method: str, path: str, body: dict | None
):
    answer = getattr(hosted, method)(path, **({} if body is None else {"json": body}))
    assert answer.status_code == 501, answer.text
    assert answer.json()["detail"] == f.unavailable_message(f.REMOTE_DIAL)


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/api/bundle/save", {}),
        ("post", "/api/file-access/export", {"dest": "/tmp/x"}),
        ("get", "/api/file-access/exports", None),
        ("post", "/api/file-access/exports/remove", {"paths": []}),
        ("post", "/api/releases/r/files/export", {"folder": "/tmp/x"}),
        ("post", "/api/releases/r/save", {"folder": "/tmp/x"}),
    ],
)
def test_path_named_exports_answer_501_on_a_host_without_them(
    hosted: TestClient, method: str, path: str, body: dict | None
):
    answer = hosted.get(path) if method == "get" else hosted.post(path, json=body or {})
    assert answer.status_code == 501, answer.text
    assert answer.json()["detail"] == f.unavailable_message(f.SERVER_PATH_EXPORT)


def test_a_bundle_streams_to_the_client_without_a_server_path(hosted: TestClient):
    hosted.post(
        "/api/schemas",
        json={"name": "s", "fields": [{"name": "n", "type": "string"}]},
    )
    answer = hosted.get("/api/bundle")
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/zip"
    assert "bundle.json" in zipfile.ZipFile(io.BytesIO(answer.content)).namelist()


def test_a_hosted_import_drops_plugins_and_workflows_and_says_so(
    hosted: TestClient, tmp_path: Path
):
    hosted.post(
        "/api/schemas",
        json={"name": "s", "fields": [{"name": "n", "type": "string"}]},
    )
    raw = _bundle_with_code(hosted.get("/api/bundle").content)
    answer = _post_bundle(hosted, raw)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["plugins"] == 0 and body["workflows"] == 0
    assert body["plugins_dropped"] == 1 and body["workflows_dropped"] == 1
    assert "s" in body["schemas_existing"]
    civex_dir = tmp_path / "hosted" / "_civex"
    assert not (civex_dir / "plugins" / "evil.py").exists()
    assert not (civex_dir / "workflows" / "flow.yaml").exists()


def test_a_local_import_installs_code_as_before(client: TestClient):
    client.post(
        "/api/schemas",
        json={"name": "s", "fields": [{"name": "n", "type": "string"}]},
    )
    raw = _bundle_with_code(client.get("/api/bundle").content)
    body = _post_bundle(client, raw).json()
    assert body["plugins"] == 1 and body["workflows"] == 1
    assert body["plugins_dropped"] == 0 and body["workflows_dropped"] == 0
    assert client.get("/api/remote").status_code == 200
