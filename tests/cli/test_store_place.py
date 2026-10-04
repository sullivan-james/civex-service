from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.config import load_config
from civex.main import app

runner = CliRunner()


def _plain(result) -> str:
    return " ".join(result.output.split())


def _setup(project_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "usb").mkdir()
    assert (
        runner.invoke(
            app, ["store", "add", "usb", "--path", str(tmp_path / "usb")]
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["collection", "create", "study"]).exit_code == 0


def test_place_set_list_clear(project_dir: Path, tmp_path: Path) -> None:
    _setup(project_dir, tmp_path)

    assert runner.invoke(app, ["store", "place", "list"]).exit_code == 0
    assert "No collection has a home volume" in _plain(
        runner.invoke(app, ["store", "place", "list"])
    )

    done = runner.invoke(
        app, ["store", "place", "set", "study", "usb", "--on-unavailable", "fail"]
    )
    assert done.exit_code == 0, done.output
    listed = _plain(runner.invoke(app, ["store", "place", "list"]))
    assert "study" in listed and "usb" in listed and "fail" in listed
    assert len(load_config().store_config.placement) == 1

    cleared = runner.invoke(app, ["store", "place", "clear", "study"])
    assert cleared.exit_code == 0
    assert load_config().store_config.placement == {}
    assert "has no placement" in _plain(
        runner.invoke(app, ["store", "place", "clear", "study"])
    )


def test_place_set_rejects_unknown_collection_volume_and_policy(
    project_dir: Path, tmp_path: Path
) -> None:
    _setup(project_dir, tmp_path)

    assert runner.invoke(app, ["store", "place", "set", "nope", "usb"]).exit_code == 1
    assert runner.invoke(app, ["store", "place", "set", "study", "nope"]).exit_code == 1
    bad = runner.invoke(
        app, ["store", "place", "set", "study", "usb", "--on-unavailable", "sometimes"]
    )
    assert bad.exit_code == 1
    assert load_config().store_config.placement == {}
