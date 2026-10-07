"""desktop-launcher/civex_launcher.py: starting, updating and restarting the
desktop app. The install itself (uv from PyPI or a wheel) is exercised by the
release workflow on every OS; these hold the loop and its records."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "civex_launcher",
    Path(__file__).resolve().parent.parent / "desktop-launcher/civex_launcher.py",
)
assert _SPEC and _SPEC.loader
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CIVEX_APP_HOME", str(tmp_path / "app"))
    monkeypatch.setattr(launcher, "bundled_uv", lambda: Path("/bundled/uv"))
    monkeypatch.setattr(launcher, "ensure_installed", lambda *a: None)
    monkeypatch.setattr(launcher, "with_progress", lambda title, msg, work: work())
    return tmp_path / "app"


def test_everything_stays_in_the_launcher_s_own_folder(home: Path) -> None:
    env = launcher.environment(home, Path("/bundled/uv"))
    assert env["UV_TOOL_DIR"] == str(home / "tools")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(home / "python")
    assert env["UV_PYTHON_PREFERENCE"] == "only-managed"
    assert env["CIVEX_UV_BIN"] == "/bundled/uv"


def test_upgrades_take_pre_releases_only_when_asked() -> None:
    uv = Path("/u/uv")
    assert launcher.upgrade_command(uv, pre=False) == [
        "/u/uv",
        "tool",
        "upgrade",
        "civex",
    ]
    assert "--prerelease" in launcher.upgrade_command(uv, pre=True)


def test_closing_the_app_ends_the_launcher(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(launcher, "run_app", lambda h, args, env: started.append(args))
    assert launcher.main([]) == 0
    assert started == [[]]


def test_an_update_request_upgrades_records_and_reopens_the_project(
    home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = tmp_path / "update-result.json"
    started: list[list[str]] = []

    def app(h: Path, args: list[str], env: dict[str, str]) -> None:
        started.append(args)
        if len(started) == 1:  # the first run asks for an update and closes
            Path(env[launcher.REQUEST_ENV]).write_text(
                json.dumps(
                    {
                        "from": "1.2.0",
                        "pre": True,
                        "result": str(result),
                        "project": "/p",
                    }
                )
            )

    ran: list[list[str]] = []
    monkeypatch.setattr(launcher, "run_app", app)
    monkeypatch.setattr(
        launcher, "run_logged", lambda cmd, env, log: ran.append(cmd) or 0
    )
    monkeypatch.setattr(launcher, "civex_version", lambda h, env: "1.3.0rc1")
    assert launcher.main([]) == 0
    assert started == [[], ["--project", "/p"]]
    assert ran == [["/bundled/uv", "tool", "upgrade", "--prerelease", "allow", "civex"]]
    record = json.loads(result.read_text())
    assert record["ok"] and (record["from"], record["to"]) == ("1.2.0", "1.3.0rc1")
    assert not (home / "update-request.json").exists()


@pytest.mark.parametrize(
    ("code", "after", "says"),
    [(1, "1.2.0", "The update failed"), (0, "1.2.0", "nothing newer")],
)
def test_a_failed_update_is_recorded_and_civex_opens_anyway(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    code: int,
    after: str,
    says: str,
) -> None:
    result = tmp_path / "update-result.json"
    started: list[list[str]] = []

    def app(h: Path, args: list[str], env: dict[str, str]) -> None:
        started.append(args)
        if len(started) == 1:
            Path(env[launcher.REQUEST_ENV]).write_text(
                json.dumps({"from": "1.2.0", "result": str(result)})
            )

    monkeypatch.setattr(launcher, "run_app", app)
    monkeypatch.setattr(launcher, "run_logged", lambda cmd, env, log: code)
    monkeypatch.setattr(launcher, "civex_version", lambda h, env: after)
    assert launcher.main([]) == 0
    assert len(started) == 2
    record = json.loads(result.read_text())
    assert not record["ok"] and says in record["message"]


def test_a_broken_request_file_is_treated_as_a_plain_close(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text("not json")
    assert launcher.take_request(path) is None
    assert not path.exists()


def test_a_built_app_never_borrows_a_uv_from_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A uv missing from the app went unnoticed on CI runners, which have
    one on PATH, and would have failed only on people's computers."""
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/uv")
    with pytest.raises(RuntimeError, match="missing its uv"):
        launcher.bundled_uv()
    inside = tmp_path / "uv" / f"uv{launcher.EXE}"
    inside.parent.mkdir()
    inside.touch()
    assert launcher.bundled_uv() == inside
