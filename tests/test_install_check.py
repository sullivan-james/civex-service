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
