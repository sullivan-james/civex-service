"""Self-repair of the SDK after an upgrade from civex <= 1.0.6 deleted its files."""

from __future__ import annotations

import pytest

from civex import _sdk_repair as repair


class _Done:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = self.stderr = ""


def test_noop_when_sdk_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []
    monkeypatch.setattr(repair.subprocess, "run", lambda *a, **k: called.append(a))
    assert repair.repair_sdk_if_needed() is False
    assert not called


def test_noop_when_sdk_never_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module missing *and* no metadata is a different problem; don't touch it."""
    monkeypatch.setattr(repair.importlib.util, "find_spec", lambda name: None)

    def _missing(name: str) -> str:
        raise repair.PackageNotFoundError(name)

    monkeypatch.setattr(repair, "version", _missing)
    assert repair._needs_repair() is None


def _broken(monkeypatch: pytest.MonkeyPatch, fixed_after: int = 1) -> list[list[str]]:
    """Module missing with metadata present, until `fixed_after` installs ran."""
    ran: list[list[str]] = []
    state = {"n": 0}

    def _spec(name: str):
        return object() if state["n"] >= fixed_after else None

    monkeypatch.setattr(repair.importlib.util, "find_spec", _spec)
    monkeypatch.setattr(repair, "version", lambda name: "0.2.0")
    monkeypatch.setattr(repair.shutil, "which", lambda name: None)

    def _run(cmd, **kwargs):
        ran.append(cmd)
        state["n"] += 1
        return _Done(0)

    monkeypatch.setattr(repair.subprocess, "run", _run)
    return ran


def test_reinstalls_same_version_without_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran = _broken(monkeypatch)
    assert repair.repair_sdk_if_needed() is True
    assert "--force-reinstall" in ran[0] and "--no-deps" in ran[0]
    assert ran[0][-1] == "civex-plugin-sdk==0.2.0"


def test_falls_back_to_uv_when_pip_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = _broken(monkeypatch, fixed_after=2)
    monkeypatch.setattr(repair.shutil, "which", lambda name: "/usr/bin/uv")
    assert repair.repair_sdk_if_needed() is True
    assert ran[1][:3] == ["/usr/bin/uv", "pip", "install"]


def test_failure_warns_with_the_manual_command_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _broken(monkeypatch, fixed_after=99)
    assert repair.repair_sdk_if_needed() is False
    err = capsys.readouterr().err
    assert "pip install --force-reinstall --no-deps civex-plugin-sdk==0.2.0" in err


def test_an_unexpected_error_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repair.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(repair, "version", lambda name: "0.2.0")

    def _boom(*a, **k):
        raise OSError("no pip")

    monkeypatch.setattr(repair.subprocess, "run", _boom)
    assert repair.repair_sdk_if_needed() is False
