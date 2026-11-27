"""The desktop app serves one project after another in one process: the server
for one stops and the next one's starts. What the sync host shows (progress,
the last result, the server's version, a connect) is about the project served,
never the one before, and a thread still finishing for that one is not revived
or shown."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from civex.config import load_config_at
from civex.context import build_local_context
from civex.domain.sync import SyncProgress
from civex.project import scaffold_project
from civex.services.sync_jobs import SyncJobs
from civex.services.sync_service import SyncReport


def _project(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    scaffold_project(root)
    return root


def _until(check, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


def test_the_next_project_does_not_show_the_last_ones_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from civex.server.app import create_app
    from civex.services.sync_jobs import sync_jobs

    first, second = _project(tmp_path, "first"), _project(tmp_path, "second")
    monkeypatch.chdir(first)
    with TestClient(create_app()):
        # What the worker had said for the first project when it was left.
        sync_jobs.worker._on_progress(SyncProgress("history", 7800, 197488))
        sync_jobs.worker._on_files(SyncProgress("files", 3, 10))
        sync_jobs.worker.last_report = SyncReport(server_version="2.3.4")
        sync_jobs.connect_error = "refused"
    monkeypatch.chdir(second)
    with TestClient(create_app()) as client:
        body = client.get("/api/remote").json()
    assert body["configured"] is False
    assert body["progress"] is None
    assert body["files_progress"] is None
    assert body["last_result"] is None
    assert body["connect_error"] is None
    assert body["connecting"] is False


def test_a_worker_still_busy_at_the_switch_is_not_revived_or_shown(
    tmp_path: Path,
):
    root = _project(tmp_path, "p")
    jobs = SyncJobs(lambda: load_config_at(root), build_local_context)
    release, busy = threading.Event(), threading.Event()
    old = jobs.worker

    def slow_tick():  # a page of history that outlasts the stop
        busy.set()
        release.wait(10)
        old._on_progress(SyncProgress("history", 7800, 197488))

    old.tick = slow_tick
    jobs.ensure_worker()
    orphan = jobs._thread
    assert orphan is not None
    _until(busy.is_set)
    jobs.shutdown()  # gives up waiting on it
    assert orphan.is_alive()

    jobs.ensure_worker()  # the next project gets a worker of its own
    assert jobs.worker is not old
    assert jobs._thread is not None and jobs._thread is not orphan
    assert jobs._thread.is_alive()

    release.set()
    orphan.join(5)
    assert not orphan.is_alive()  # its stop stayed set: it ended
    assert jobs.history_progress is None
    assert jobs.progress is None
    jobs.shutdown()


def test_a_copy_still_running_does_not_hold_up_or_touch_the_next_project(
    tmp_path: Path,
):
    release = threading.Event()
    started: list[str] = []

    class _Sync:
        def __init__(self, name: str) -> None:
            self.name = name

        def connect(self, url, invite, progress, login):
            started.append(self.name)
            progress(SyncProgress("copying", 1, 10))
            if self.name == "first":
                release.wait(10)
                progress(SyncProgress("copying", 9, 10))
                raise RuntimeError("cut off")

    current = {"name": "first"}

    def open_context(config):
        return SimpleNamespace(
            sync_svc=_Sync(config), commit=lambda: None, close=lambda: None
        )

    jobs = SyncJobs(lambda: current["name"], open_context)
    jobs.start_connect("https://example.org/a")
    _until(lambda: started == ["first"])
    first = jobs._connecting
    jobs.shutdown()
    assert not jobs.connecting and jobs.copy_progress is None

    current["name"] = "second"
    jobs.worker.tick = jobs.worker.files_tick = lambda: None  # started after
    jobs.start_connect("https://example.org/b")  # not swallowed
    _until(lambda: started == ["first", "second"])
    jobs._connecting.join(5)

    release.set()
    first.join(5)
    assert jobs.connect_error is None  # the first one's failure is its own
    assert jobs.copy_progress is None
    jobs.shutdown()


def test_history_is_never_shown_while_a_copy_runs(tmp_path: Path):
    """The app says the project is ready to use while history arrives."""
    release = threading.Event()

    class _Sync:
        def connect(self, url, invite, progress, login):
            release.wait(10)

    jobs = SyncJobs(
        lambda: None,
        lambda config: SimpleNamespace(
            sync_svc=_Sync(), commit=lambda: None, close=lambda: None
        ),
    )
    jobs.history_progress = SyncProgress("history", 7800, 197488)
    jobs.worker.tick = jobs.worker.files_tick = lambda: None  # started after
    jobs.start_connect("https://example.org/a")
    try:
        assert jobs.connecting
        assert jobs.progress is None  # not "ready to use" before the first page
    finally:
        release.set()
        jobs._connecting.join(5)
    assert jobs.progress == SyncProgress("history", 7800, 197488)
    jobs.shutdown()
