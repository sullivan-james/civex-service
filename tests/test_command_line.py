"""civex.command_line: putting the desktop app's civex on PATH, and back."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex import command_line


@pytest.fixture
def app_bin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """This process as the desktop app's civex, with a home of its own."""
    folder = tmp_path / "app" / "bin"
    folder.mkdir(parents=True)
    (folder / "civex").write_text("#!/bin/sh\n")
    (folder / "civex").chmod(0o755)
    monkeypatch.setattr(command_line, "detect_installer", lambda: "desktop")
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(folder))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    local_bin = tmp_path / "home" / ".local" / "bin"
    monkeypatch.setattr(command_line, "_shell_path", lambda: [str(local_bin)])
    return folder


def test_only_the_desktop_app_s_copy_is_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command_line, "detect_installer", lambda: "uv")
    found = command_line.state()
    assert not found.available and "already a command" in found.note
    with pytest.raises(command_line.CommandLineError):
        command_line.add()


@pytest.mark.posix_only
def test_adding_links_it_and_removing_takes_only_our_link(app_bin: Path) -> None:
    assert not command_line.state().on_path
    added = command_line.add()
    link = Path(added.where or "")
    assert added.on_path and link.is_symlink() and link.resolve() == app_bin / "civex"
    assert added.note == "" and added.shadowed_by is None
    assert command_line.add().on_path  # again: nothing changes
    assert not command_line.remove().on_path and not link.exists()


@pytest.mark.posix_only
def test_another_civex_in_the_link_s_place_is_left_alone(
    app_bin: Path, tmp_path: Path
) -> None:
    link = tmp_path / "home" / ".local" / "bin" / "civex"
    link.parent.mkdir(parents=True)
    link.write_text("someone else's")
    with pytest.raises(command_line.CommandLineError, match="already another civex"):
        command_line.add()
    command_line.remove()
    assert link.read_text() == "someone else's"


@pytest.mark.posix_only
def test_it_says_when_the_shell_does_not_look_in_local_bin(
    monkeypatch: pytest.MonkeyPatch, app_bin: Path
) -> None:
    monkeypatch.setattr(command_line, "_shell_path", lambda: ["/usr/bin"])
    found = command_line.add()
    assert found.on_path and ".local/bin to your shell's PATH" in found.note


@pytest.mark.posix_only
def test_another_civex_earlier_on_path_is_named(
    monkeypatch: pytest.MonkeyPatch, app_bin: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "civex").write_text("#!/bin/sh\n")
    (other / "civex").chmod(0o755)
    local_bin = tmp_path / "home" / ".local" / "bin"
    monkeypatch.setattr(
        command_line, "_shell_path", lambda: [str(other), str(local_bin)]
    )
    assert command_line.add().shadowed_by == str(other / "civex")


def test_windows_adds_and_removes_the_user_path_entry(
    monkeypatch: pytest.MonkeyPatch, app_bin: Path
) -> None:
    user = ["C:\\Tools"]
    monkeypatch.setattr(command_line.sys, "platform", "win32")
    # Only the PATH entry is under test here; looking a command up on PATH
    # isn't something to fake Windows for.
    monkeypatch.setattr(command_line, "_first_civex", lambda path: None)
    monkeypatch.setattr(command_line, "_user_path", lambda: list(user))
    monkeypatch.setattr(
        command_line,
        "_set_user_path",
        lambda entries: user.__setitem__(slice(None), entries),
    )
    assert command_line.add().on_path
    assert user == ["C:\\Tools", str(app_bin)]
    command_line.add()
    assert user.count(str(app_bin)) == 1
    assert not command_line.remove().on_path
    assert user == ["C:\\Tools"]


def test_the_endpoints(app_bin: Path) -> None:
    from civex.server.app import create_app

    client = TestClient(create_app())
    assert client.get("/api/settings/command-line").json()["available"]
    added = client.post("/api/settings/command-line").json()
    assert added["on_path"]
    assert not client.delete("/api/settings/command-line").json()["on_path"]
