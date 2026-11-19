"""The desktop window moving between projects and back to the start screen:
one server at a time, each in its own project's folder."""

from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path

import pytest

from civex.project import scaffold_project


class _Window:
    """What the tray asks of a pywebview window, recorded."""

    def __init__(self) -> None:
        self.pages: list[tuple[str, str]] = []

    def load_url(self, url: str) -> None:
        self.pages.append(("url", url))

    def load_html(self, text: str) -> None:
        self.pages.append(("html", text))

    def urls(self) -> list[str]:
        return [value for kind, value in self.pages if kind == "url"]


def _answers(url: str) -> bool:
    try:
        urllib.request.urlopen(f"{url}/health", timeout=1).close()
        return True
    except OSError:
        return False


def _until(check, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


@pytest.fixture
def tray(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import civex.desktop.tray as tray

    monkeypatch.chdir(tmp_path)  # the tray changes folder; put it back after
    window = _Window()
    monkeypatch.setattr(tray, "_window", window)
    monkeypatch.setattr(tray, "_save_recent", lambda path: None)
    monkeypatch.setattr(tray, "_place_project_window", lambda w: None)
    yield tray
    with tray._switching:
        tray._server.stop()


def test_opening_another_project_stops_the_first_and_serves_the_second(
    tray, tmp_path: Path
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for folder in (first, second):
        folder.mkdir()
        scaffold_project(folder)
    window = tray._window

    tray._launch_project(first)
    _until(lambda: len(window.urls()) == 1)
    one = window.urls()[0]
    assert _answers(one)

    tray._launch_project(second)
    _until(lambda: len(window.urls()) == 2)
    two = window.urls()[1]
    assert _answers(two)
    assert not _answers(one)  # not left running against the wrong folder
    assert Path(os.getcwd()) == second


def test_the_start_screen_shows_at_once_and_the_server_stops(
    tray, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    scaffold_project(project)
    window = tray._window
    tray._launch_project(project)
    _until(lambda: len(window.urls()) == 1)
    url = window.urls()[0]

    assert tray._Api().show_start() == {"ok": True}
    assert window.pages[-1] == ("html", tray._WELCOME_HTML)
    _until(lambda: not _answers(url))  # stops behind the start screen


def test_a_server_that_ends_while_starting_is_reported_at_once(
    tray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not after waiting the whole 30 s for a server that is already gone."""
    import uvicorn

    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    started = time.monotonic()
    tray._launch_project(Path.cwd())
    _until(lambda: tray._window.pages)
    assert time.monotonic() - started < 5
    kind, text = tray._window.pages[-1]
    assert kind == "html" and "stopped while starting" in text
    assert "show_start" in text  # a way back to the start screen
