from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from civex import install_check as ic


def _fake_civex(directory: Path, version: str) -> Path:
    directory.mkdir()
    if sys.platform == "win32":
        path = directory / "civex.bat"
        path.write_text(f"@echo civex {version}\r\n")
    else:
        path = directory / "civex"
        path.write_text(f"#!/bin/sh\necho civex {version}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_lists_every_copy_in_path_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = _fake_civex(tmp_path / "a", "1.0.0"), _fake_civex(tmp_path / "b", "2.0.0")
    monkeypatch.setenv("PATH", os.pathsep.join([str(a.parent), str(b.parent)]))
    assert ic.executables_on_path("civex") == [a, b]


def test_a_stale_copy_first_on_path_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new = (
        _fake_civex(tmp_path / "old", "1.0.0"),
        _fake_civex(tmp_path / "new", "2.0.0"),
    )
    monkeypatch.setenv("PATH", os.pathsep.join([str(old.parent), str(new.parent)]))
    check = ic.check_shadowing("2.0.0")
    assert check.status == "warn"
    assert str(old) in check.detail and "1.0.0" in check.detail
    assert str(new) in check.detail and check.fix


def test_the_right_copy_first_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    new = _fake_civex(tmp_path / "new", "2.0.0")
    monkeypatch.setenv("PATH", str(new.parent))
    assert ic.check_shadowing("2.0.0").status == "ok"


def test_no_civex_on_path_is_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert ic.check_shadowing("2.0.0").status == "warn"


def test_a_missing_dependency_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "importlib.metadata.requires", lambda name: ["definitely-not-installed-pkg>=1"]
    )
    assert ic.missing_requirements() == ["definitely-not-installed-pkg>=1"]
    assert ic.check_dependencies().status == "fail"


def test_this_environment_has_what_civex_needs() -> None:
    assert ic.missing_requirements() == []


def _fake_env(cache: Path, name: str, home: Path) -> Path:
    env = cache / "environments-v2" / name
    env.mkdir(parents=True)
    (env / "pyvenv.cfg").write_text(f"home = {home}\nimplementation = CPython\n")
    return env


def _python_home(tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir()
    (home / ("python.exe" if sys.platform == "win32" else "python")).write_text("")
    return home


def test_an_environment_whose_python_is_gone_is_stale(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    good = _fake_env(cache, "good", _python_home(tmp_path, "py"))
    gone = _fake_env(cache, "gone", tmp_path / "Temp" / "civex-plugin-x" / "Python")
    assert ic.stale_environments(cache) == [gone]
    assert good.exists()


def test_a_missing_cache_has_nothing_stale(tmp_path: Path) -> None:
    assert ic.stale_environments(tmp_path / "nope") == []


def test_removing_leaves_good_environments_alone(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    good = _fake_env(cache, "good", _python_home(tmp_path, "py"))
    gone = _fake_env(cache, "gone", tmp_path / "missing")
    assert ic.remove_stale_environments(cache) == [gone]
    assert good.exists() and not gone.exists()
    assert ic.remove_stale_environments(cache) == []


def test_doctor_fix_removes_stale_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from civex.main import app

    cache = tmp_path / "cache"
    gone = _fake_env(cache, "gone", tmp_path / "missing")
    monkeypatch.setattr(ic, "uv_cache_dir", lambda: cache)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["doctor", "--fix"])
    assert "Removed 1" in result.output
    assert not gone.exists()


def test_the_plugin_error_points_at_the_fix() -> None:
    import io

    from civex.plugins.subprocess_runtime import _dead_process_message

    class _Proc:
        stderr = io.StringIO("did not find executable at 'C:\\\\x\\\\python.exe'")

        def poll(self) -> None:
            return None

    assert "civex doctor --fix" in _dead_process_message(_Proc())  # type: ignore[arg-type]
