"""civex.updates and its helper: updating civex from the app, after it exits."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex import updates

_SPEC = importlib.util.spec_from_file_location(
    "update_helper", Path(updates.__file__).with_name("_update_helper.py")
)
assert _SPEC and _SPEC.loader
helper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helper)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVEX_USER_STATE", str(tmp_path / "state" / "sync.toml"))
    for name in (updates.REQUEST_ENV, updates.SERVE_ARGS_ENV, "CIVEX_ALLOW_REMOTE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(updates, "_quit_app", None)


# -- Can this copy update itself? --------------------------------------------


def test_an_editable_or_old_frozen_copy_cannot() -> None:
    assert "development (editable) install" in updates.why_not(
        "editable", from_app=False
    )
    assert "Download the current desktop app" in updates.why_not(
        "frozen", from_app=False
    )


def test_uv_installs_need_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates.shutil, "which", lambda name: None)
    assert "isn't on PATH" in updates.why_not("uv", from_app=False)
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/bin/" + name)
    assert updates.why_not("uv", from_app=False) == ""


def test_from_the_app_the_server_must_be_able_to_start_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "wasn't started with `civex serve`" in updates.why_not("pip", from_app=True)
    monkeypatch.setenv(updates.SERVE_ARGS_ENV, '["serve"]')
    assert updates.why_not("pip", from_app=True) == ""
    monkeypatch.setenv("CIVEX_ALLOW_REMOTE", "1")
    assert "--allow-remote" in updates.why_not("pip", from_app=True)
    # The CLI is run by the person at the server, so neither applies to it.
    assert updates.why_not("pip", from_app=False) == ""


def test_the_desktop_launcher_is_recognised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(updates.REQUEST_ENV, str(tmp_path / "request.json"))
    assert updates.detect_installer() == "desktop"
    assert updates.why_not("desktop", from_app=True) == ""


def test_restarting_does_not_open_another_tab() -> None:
    assert updates.restart_args(["serve", "--port", "9000", "--open"]) == [
        "serve",
        "--port",
        "9000",
    ]


# -- Checking ------------------------------------------------------------------


def test_check_reports_newer_and_why_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates, "__version__", "1.2.0")
    monkeypatch.setattr(updates, "detect_installer", lambda: "editable")
    found = updates.check(pre=True, fetch=lambda pre: "1.3.0rc1" if pre else "1.2.0")
    assert (found.latest, found.newer, found.pre) == ("1.3.0rc1", True, True)
    assert "development (editable) install" in found.blocked


def test_check_says_when_pypi_cannot_be_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def offline(pre: bool) -> str:
        raise OSError("no network")

    found = updates.check(fetch=offline)
    assert found.latest is None and not found.newer
    assert "no network" in found.error


# -- Handing over --------------------------------------------------------------


def test_the_desktop_app_asks_its_launcher_and_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request = tmp_path / "request.json"
    monkeypatch.setenv(updates.REQUEST_ENV, str(request))
    with pytest.raises(RuntimeError, match="can't be closed"):
        updates.begin(pre=False)
    closed: list[bool] = []
    updates.on_quit_for_update(lambda: closed.append(True))
    exit_now = updates.begin(pre=True)
    asked = json.loads(request.read_text())
    assert asked["pre"] is True and asked["result"] == str(updates.result_path())
    assert not closed  # the caller closes it, once its answer is sent
    exit_now()
    assert closed == [True]


def test_civex_serve_hands_over_to_the_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(updates, "detect_installer", lambda: "pip")
    monkeypatch.setenv(updates.SERVE_ARGS_ENV, '["serve", "--port", "9000", "--open"]')
    plans: list[dict] = []
    monkeypatch.setattr(updates, "_start_helper", plans.append)
    assert updates.begin(pre=True) is updates._stop_server
    (plan,) = plans
    assert plan["upgrade"][-3:] == ["--upgrade", "--pre", "civex"]
    assert plan["restart"][-4:] == ["civex.main", "serve", "--port", "9000"]
    assert plan["wait_pid"] > 0


def test_a_copy_that_cannot_update_refuses_to_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(updates, "detect_installer", lambda: "editable")
    with pytest.raises(RuntimeError, match="development"):
        updates.begin(pre=False)


# -- The helper ----------------------------------------------------------------


def _plan(tmp_path: Path, *, upgrade: str, version: str) -> Path:
    py = sys.executable
    started = tmp_path / "started"
    gone = subprocess.Popen([py, "-c", "pass"])
    gone.wait()
    plan = {
        "from": "1.2.0",
        "pre": False,
        "result": str(tmp_path / "result.json"),
        "wait_pid": gone.pid,
        "upgrade": [py, "-c", upgrade],
        "version": [py, "-c", f"print({version!r})"],
        "restart": [py, "-c", f"open({str(started)!r}, 'w').close()"],
        "cwd": str(tmp_path),
        "log": str(tmp_path / "update.log"),
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def test_the_helper_upgrades_records_and_starts_civex_again(tmp_path: Path) -> None:
    plan = _plan(tmp_path, upgrade="pass", version="1.3.0")
    assert helper.main(str(plan)) == 0
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["ok"] is True and (result["from"], result["to"]) == ("1.2.0", "1.3.0")
    _wait_for(tmp_path / "started")


@pytest.mark.parametrize(
    ("upgrade", "says"),
    [("raise SystemExit(3)", "exit 3"), ("pass", "still the same version")],
)
def test_a_failed_update_still_starts_the_old_civex(
    tmp_path: Path, upgrade: str, says: str
) -> None:
    plan = _plan(tmp_path, upgrade=upgrade, version="1.2.0")
    helper.main(str(plan))
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["ok"] is False and says in result["message"]
    _wait_for(tmp_path / "started")
    assert updates.last_result() is None  # isolated from this test's result file


# -- The API -------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    from civex.server.app import create_app

    return TestClient(create_app())


def test_status_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates, "latest_version", lambda pre=False: "99.0.0")
    monkeypatch.setattr(updates, "detect_installer", lambda: "editable")
    body = client.get("/api/update?pre=true").json()
    assert body["latest"] == "99.0.0" and body["newer"] and body["pre"]
    assert not body["can_update"] and body["blocked"]


def test_starting_an_update_answers_then_exits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    exited: list[bool] = []
    monkeypatch.setattr(updates, "begin", lambda pre: lambda: exited.append(pre))
    response = client.post("/api/update", json={"pre": False})
    assert response.status_code == 202 and response.json() == {"restarting": True}
    deadline = time.monotonic() + 5
    while not exited:
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_starting_an_update_that_cannot_happen_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(updates, "detect_installer", lambda: "editable")
    response = client.post("/api/update", json={"pre": False})
    assert response.status_code == 409
    assert "development (editable) install" in response.json()["detail"]
