"""civex.running: what runs from a copy of civex, so an update can stop it and
start it again."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex import running, updates
from civex.processes import pid_alive


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVEX_USER_STATE", str(tmp_path / "state" / "sync.toml"))
    monkeypatch.setenv("CIVEX_APP_HOME", str(tmp_path / "app"))
    monkeypatch.setattr(running, "_mine", None)


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def _record(pid: int, prefix: str | None = None, **over) -> running.Running:
    record = running.Running(
        pid=pid,
        prefix=prefix or sys.prefix,
        argv=["serve", "--port", "8100", "--allow-remote"],
        cwd=str(Path.cwd()),
        host="127.0.0.1",
        port=8100,
        token="secret",
        started="2026-10-08T12:00:00Z",
        **over,
    )
    folder = running.running_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pid}.json").write_text(json.dumps(record.to_dict()))
    return record


def test_a_server_says_it_is_running_and_only_others_of_this_copy_are_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(running.atexit, "register", lambda *a: None)
    mine = running.register("127.0.0.1", 8000)
    assert (running.running_dir() / f"{mine.pid}.json").exists()
    assert running.accepts_stop(mine.token) and not running.accepts_stop("guess")

    other = _sleeper()
    elsewhere = _sleeper()
    try:
        _record(other.pid)
        _record(elsewhere.pid, prefix=str(tmp_path / "another-copy"))
        _record(999_999_99)  # long gone
        found = running.others()
        assert [r.pid for r in found] == [other.pid]  # not itself, not elsewhere
        assert found[0].describe().startswith("civex serve --port 8100")
        assert not (running.running_dir() / "99999999.json").exists()
    finally:
        other.kill()
        elsewhere.kill()


def test_a_server_that_does_not_answer_is_made_to_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    proc = _sleeper()
    # Reaped as soon as it ends, as a server that isn't our child would be.
    threading.Thread(target=proc.wait, daemon=True).start()
    record = _record(proc.pid)
    monkeypatch.setattr(running, "_ask_to_stop", lambda r: False)
    try:
        assert running.stop(record, seconds=0.1)
        proc.wait(timeout=10)
        assert not pid_alive(proc.pid)
        assert not (running.running_dir() / f"{proc.pid}.json").exists()
    finally:
        proc.kill()


def test_it_starts_again_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record(1234)
    command = running.start_command(record)
    assert command[1:] == [
        "-m",
        "civex.main",
        "serve",
        "--port",
        "8100",
        "--allow-remote",
    ]
    assert Path(command[0]).parent.parent == Path(sys.prefix)

    started: list[running.Running] = []
    monkeypatch.setattr(running, "start", started.append)
    running.remember([record])
    assert [r.pid for r in running.start_remembered()] == [1234]
    assert started == [record]
    assert running.start_remembered() == []  # once


def test_the_stop_endpoint_needs_the_servers_own_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from civex.server.app import create_app

    monkeypatch.setattr(running.atexit, "register", lambda *a: None)
    mine = running.register("127.0.0.1", 8000)
    stopped: list[bool] = []
    monkeypatch.setattr(updates, "_stop_server", lambda: stopped.append(True))
    client = TestClient(create_app())
    assert client.post("/api/server/stop").status_code == 403
    assert (
        client.post(
            "/api/server/stop", headers={running.STOP_HEADER: "nope"}
        ).status_code
        == 403
    )
    answer = client.post("/api/server/stop", headers={running.STOP_HEADER: mine.token})
    assert answer.status_code == 202
    import time

    deadline = time.monotonic() + 5
    while not stopped:
        assert time.monotonic() < deadline
        time.sleep(0.05)
