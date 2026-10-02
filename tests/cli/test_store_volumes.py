from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def _plain(result) -> str:
    return " ".join(result.output.split())


def test_list_explains_an_offline_volume_and_how_to_fix_it(
    project_dir: Path, tmp_path: Path
) -> None:
    drive = tmp_path / "usb"
    drive.mkdir()
    assert (
        runner.invoke(app, ["store", "add", "usb", "--path", str(drive)]).exit_code == 0
    )
    drive.rename(tmp_path / "usb-unplugged")

    result = runner.invoke(app, ["store", "list"])

    assert result.exit_code == 0
    out = _plain(result)
    assert "offline" in out
    assert "path missing" in out
    assert "civex store update usb" in out


def test_wrong_drive_is_reported_and_adopt_fixes_it(
    project_dir: Path, tmp_path: Path
) -> None:
    drive = tmp_path / "usb"
    drive.mkdir()
    runner.invoke(app, ["store", "add", "usb", "--path", str(drive)])
    (drive / ".civex-volume").unlink()

    listed = runner.invoke(app, ["store", "list"])
    assert "wrong drive" in _plain(listed)
    assert "civex store adopt usb" in _plain(listed)

    declined = runner.invoke(app, ["store", "adopt", "usb"], input="n\n")
    assert declined.exit_code == 1
    assert not (drive / ".civex-volume").exists()

    adopted = runner.invoke(app, ["store", "adopt", "usb", "--yes"])
    assert adopted.exit_code == 0
    assert (drive / ".civex-volume").exists()
    assert "wrong drive" not in _plain(runner.invoke(app, ["store", "list"]))


def test_adding_another_volumes_drive_is_refused_cleanly(
    project_dir: Path, tmp_path: Path
) -> None:
    drive = tmp_path / "usb"
    drive.mkdir()
    runner.invoke(app, ["store", "add", "usb", "--path", str(drive)])

    result = runner.invoke(app, ["store", "add", "other", "--path", str(drive)])

    assert result.exit_code == 1
    assert "drive of volume 'usb'" in _plain(result)
    assert "other" not in _plain(runner.invoke(app, ["store", "list"]))
