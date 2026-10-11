"""The server's background hosts open contexts through a factory they are
given, so a host serving many projects can run them per project; `civex serve`
gives each the project in its directory."""

from __future__ import annotations

from pathlib import Path

from civex.config import load_config_at
from civex.context import build_local_context, local_context
from civex.project import scaffold_project
from civex.services.history_jobs import HistoryJobs
from civex.services.sync_jobs import SyncJobs
from civex.services.transfer_jobs import TransferJobs


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    scaffold_project(root)
    return root


def test_history_conversion_runs_on_the_project_it_is_given(tmp_path: Path):
    root = _project(tmp_path)
    opened: list[Path] = []

    def make_context():
        opened.append(root)
        return build_local_context(load_config_at(root))

    jobs = HistoryJobs(make_context)
    jobs.ensure_running()
    jobs.shutdown()
    assert opened == [root]
    assert jobs.error is None


def test_transfers_open_contexts_through_the_factory(tmp_path: Path):
    root = _project(tmp_path)
    opened: list[Path] = []

    def make_context():
        opened.append(root)
        return build_local_context(load_config_at(root))

    jobs = TransferJobs(make_context)
    ctx = jobs._context()
    try:
        assert ctx.config.project_root == root
    finally:
        ctx.close()
    assert opened == [root]


def test_sync_jobs_take_how_to_find_and_open_the_project(tmp_path: Path):
    root = _project(tmp_path)
    jobs = SyncJobs(lambda: load_config_at(root), build_local_context)
    assert jobs.worker._load_config().project_root == root


def test_the_default_is_the_project_in_the_current_directory(
    tmp_path: Path, monkeypatch
):
    root = _project(tmp_path)
    monkeypatch.chdir(root)
    ctx = local_context()
    try:
        assert ctx.config.project_root == root
    finally:
        ctx.close()
