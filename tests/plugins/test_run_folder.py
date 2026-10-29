"""Files go by path, in one folder per workflow run: what a step writes there
lives until the run ends, so a later step can read it, and a plugin may hand
back only files inside it."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from civex.domain.exceptions import PluginExecutionError
from civex.plugins import runtime
from civex.plugins.launchers import CommandLauncher

_PLUGIN = """\
import os
from pathlib import Path
from typing import Any
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, IOSpec, Plugin, serve

class P(Plugin):
    id = "test.files"
    name = "Files"
    capabilities = ["read", "manage_files"]
    inputs = [IOSpec(name="blob", type="bytes", required=False)]
    outputs = [IOSpec(name="blob", type="bytes"), IOSpec(name="size", type="number")]

    class Config(BaseModel):
        pass

    def invoke(self, inputs: dict[str, Any], config, ctx: Ctx) -> dict:
        what = inputs.get("do")
        if what == "make":
            return {"blob": b"x" * 2_000_000, "size": 0}
        if what == "measure":
            return {"blob": b"", "size": len(inputs["blob"])}
        if what == "path":
            p = ctx.file_path("abc")
            return {"blob": b"", "size": p.stat().st_size, "where": str(p)}
        if what == "store":
            out = ctx.run_dir / "made.txt"
            out.write_text("made here")
            return {"blob": b"", "size": 0, "file": ctx.store_path(out, "made.txt")}
        if what == "store_elsewhere":
            return {"blob": b"", "size": 0, "file": ctx.store_path(inputs["at"], "x")}
        if what == "leak":
            return {"blob": {"encoding": "path", "path": inputs["at"]}, "size": 0}
        return {}

if __name__ == "__main__":
    serve(P)
"""


class _Ctx:
    """The host side of a run, with the run folder the executor would make."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.stored: list[tuple[Path, str]] = []

    def copy_file(self, sha256: str, dest: Path) -> None:
        dest.write_bytes(b"0123456789")

    def store_path(self, path: Path, filename: str):
        self.stored.append((path, filename))

        class Ref:
            def to_dict(self) -> dict:
                return {
                    "sha256": "s",
                    "filename": filename,
                    "size": path.stat().st_size,
                }

        return Ref()


@pytest.fixture
def plugin(tmp_path: Path) -> CommandLauncher:
    script = tmp_path / "files_plugin.py"
    script.write_text(_PLUGIN)
    return CommandLauncher([sys.executable, str(script)])


@pytest.fixture
def ctx(tmp_path: Path) -> _Ctx:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return _Ctx(run_dir)


def _run(launcher: CommandLauncher, ctx: _Ctx, **inputs: Any) -> dict:
    from civex_plugin_sdk.plugin_base import IOSpec

    return runtime.run(
        launcher,
        inputs,
        {},
        ctx,  # type: ignore[arg-type]
        ["read", "manage_files"],
        20,
        input_specs=[IOSpec(name="blob", type="bytes", required=False)],
    ).outputs


def test_a_large_value_lives_in_the_run_folder_until_a_later_step_reads_it(
    plugin: CommandLauncher, ctx: _Ctx
) -> None:
    """The same plugin running again in between (its process reused, its own
    working folder emptied) doesn't take the first step's value away."""
    made = _run(plugin, ctx, do="make")["blob"]
    assert made["encoding"] == "path"
    assert Path(made["path"]).parent == ctx.run_dir.resolve()
    _run(plugin, ctx, do="make")
    assert _run(plugin, ctx, do="measure", blob=made)["size"] == 2_000_000


def test_a_plugin_gets_a_file_as_a_path_in_the_run_folder(
    plugin: CommandLauncher, ctx: _Ctx
) -> None:
    out = _run(plugin, ctx, do="path")
    assert out["size"] == 10
    assert Path(out["where"]) == ctx.run_dir / "files" / "abc"


def test_a_plugin_stores_a_file_it_wrote_in_the_run_folder(
    plugin: CommandLauncher, ctx: _Ctx
) -> None:
    out = _run(plugin, ctx, do="store")
    assert out["file"]["filename"] == "made.txt"
    assert ctx.stored == [((ctx.run_dir / "made.txt").resolve(), "made.txt")]


def test_a_file_elsewhere_is_refused(
    plugin: CommandLauncher, ctx: _Ctx, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("not the plugin's")
    with pytest.raises(PluginExecutionError) as e:
        _run(plugin, ctx, do="store_elsewhere", at=str(secret))
    assert e.value.kind == "path_refused"
    assert ctx.stored == []


def test_an_answer_pointing_outside_the_run_folder_is_refused(
    plugin: CommandLauncher, ctx: _Ctx, tmp_path: Path
) -> None:
    """The next step may run in civex's own process and read what it names."""
    with pytest.raises(PluginExecutionError) as e:
        _run(plugin, ctx, do="leak", at=str(tmp_path / "secret.txt"))
    assert e.value.kind == "path_refused"


def test_a_step_run_on_its_own_gets_a_folder_that_goes_with_it(
    plugin: CommandLauncher, ctx: _Ctx
) -> None:
    ctx.run_dir = None  # type: ignore[assignment]
    out = _run(plugin, ctx, do="make")
    assert not Path(out["blob"]["path"]).exists()


def test_the_executor_removes_the_run_folder_when_the_run_ends() -> None:
    from civex.workflows import executor
    from civex.workflows.definition import WorkflowDef

    class Ctx:
        run_dir = None
        record = type("R", (), {"id": "r"})()

    ctx = Ctx()
    seen: list[Path] = []
    real = executor._run

    def spy(wf, c, *a):
        seen.append(c.run_dir)
        assert c.run_dir.is_dir()
        return real(wf, c, *a)

    executor._run = spy  # type: ignore[assignment]
    try:
        executor.run(WorkflowDef(name="wf", steps=[]), ctx, {})  # type: ignore[arg-type]
    finally:
        executor._run = real  # type: ignore[assignment]
    assert seen and not seen[0].exists() and ctx.run_dir is None


def test_folders_a_crashed_run_left_are_removed_once_a_day_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVEX_RUNS_DIR", str(tmp_path / "runs"))
    old = runtime.new_run_dir()
    recent = runtime.new_run_dir()
    day_ago = time.time() - runtime.STALE_RUN_SECONDS - 60
    os.utime(old, (day_ago, day_ago))
    fresh = runtime.new_run_dir()
    assert not old.exists() and recent.exists() and fresh.exists()


def test_a_container_mounts_the_run_folder_at_the_same_path() -> None:
    from civex.plugins import container_runtime as cr

    argv = cr._build_command("docker", "img", "run", "n", mounts=[Path("/r/x")])
    assert argv[argv.index("--volume") + 1] == "/r/x:/r/x"
