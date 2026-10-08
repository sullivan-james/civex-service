"""How the desktop window is started: `civex desktop`, and its log."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.main import app


def test_civex_desktop_says_what_to_install_without_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "webview", None)  # import fails
    result = CliRunner().invoke(app, ["desktop"])
    assert result.exit_code == 1
    assert "civex[desktop]" in result.output


def test_the_window_logs_where_the_launcher_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CIVEX_LOG_DIR", str(tmp_path))
    import civex.desktop.tray as tray

    tray = importlib.reload(tray)
    try:
        assert tray._LOG_FILE == tmp_path / "civex-desktop.log"
    finally:
        monkeypatch.delenv("CIVEX_LOG_DIR")
        importlib.reload(tray)


def test_there_is_no_civex_desktop_command() -> None:
    import tomllib

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    )
    scripts = pyproject["project"].get("scripts", {})
    assert "civex-desktop" not in scripts
    assert "civex-desktop" not in pyproject["project"].get("gui-scripts", {})


# -- Where the project window opens -------------------------------------------


@pytest.mark.parametrize(
    ("screen", "saved", "expected"),
    [
        # A 13-inch MacBook Pro (2016): no room around a window, so it fills it.
        ((0, 0, 1280, 800), None, ("maximize", 0, 0, 1280, 800)),
        ((0, 0, 1440, 900), None, ("maximize", 0, 0, 1440, 900)),
        # A larger screen: a comfortable size, centred.
        ((0, 0, 2560, 1440), None, ("place", 640, 290, 1280, 860)),
        # As it was left, kept on the screen.
        (
            (0, 0, 1920, 1080),
            {"x": 1800, "y": -50, "width": 3000, "height": 700},
            ("place", 0, 0, 1920, 700),
        ),
        ((0, 0, 2560, 1440), {"maximized": True}, ("maximize", 0, 0, 2560, 1440)),
        # Nothing known about the screen.
        (None, None, ("place", 0, 0, 1280, 860)),
    ],
)
def test_the_project_window_fits_the_screen(screen, saved, expected) -> None:
    from civex.desktop.tray import window_place

    assert window_place(screen, saved) == expected
