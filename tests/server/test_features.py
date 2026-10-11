"""What a server does is said once (`domain.features`): a host that does less
leaves routers out and answers 501 on what is left, and the app reads the same
answer from `GET /api/status/features`."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.domain import features as f
from civex.project import Project, scaffold_project
from civex.server.app import api_routers, create_app

HOSTED = f.LOCAL_FEATURES - {f.VOLUMES, f.TERMINAL, f.DESKTOP, f.LOCAL_WORKFLOWS}


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
    everything = {id(r) for r, _ in api_routers()}
    narrowed = {id(r) for r, _ in api_routers(HOSTED)}
    gone = {id(r) for r, feature in api_routers() if feature and feature not in HOSTED}
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
