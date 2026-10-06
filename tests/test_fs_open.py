"""Showing a folder in the file manager picks the right launcher per platform."""

from __future__ import annotations

from pathlib import Path

import pytest

from civex import fs_open


def test_linux_uses_xdg_open(monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr(fs_open.sys, "platform", "linux")
    monkeypatch.setattr(fs_open, "is_wsl", lambda: False)
    monkeypatch.setattr(fs_open.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        fs_open.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd)
    )

    assert fs_open.open_folder(Path("/data/out")) is True
    assert launched == [["xdg-open", "/data/out"]]


def test_wsl_opens_windows_explorer_on_the_converted_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched: list[list[str]] = []

    class Done:
        stdout = "\\\\wsl$\\Ubuntu\\data\\out\n"

    monkeypatch.setattr(fs_open.sys, "platform", "linux")
    monkeypatch.setattr(fs_open, "is_wsl", lambda: True)
    monkeypatch.setattr(fs_open.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(fs_open.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(
        fs_open.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd)
    )

    assert fs_open.open_folder(Path("/data/out")) is True
    assert launched == [["explorer.exe", "\\\\wsl$\\Ubuntu\\data\\out"]]


def test_a_machine_with_no_desktop_just_says_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_open.sys, "platform", "linux")
    monkeypatch.setattr(fs_open, "is_wsl", lambda: False)
    monkeypatch.setattr(fs_open.shutil, "which", lambda name: None)

    assert fs_open.open_folder(Path("/data/out")) is False


def test_a_launcher_that_fails_to_start_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*a, **k):
        raise OSError("no")

    monkeypatch.setattr(fs_open.sys, "platform", "darwin")
    monkeypatch.setattr(fs_open.subprocess, "Popen", boom)

    assert fs_open.open_folder(Path("/x")) is False
