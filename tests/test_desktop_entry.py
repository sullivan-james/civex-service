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
