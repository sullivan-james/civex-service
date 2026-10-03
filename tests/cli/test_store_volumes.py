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


def test_adding_another_volumes_folder_is_refused_cleanly(
    project_dir: Path, tmp_path: Path
) -> None:
    drive = tmp_path / "usb"
    drive.mkdir()
    runner.invoke(app, ["store", "add", "usb", "--path", str(drive)])

    result = runner.invoke(app, ["store", "add", "other", "--path", str(drive)])

    assert result.exit_code == 1
    assert "already the volume 'usb'" in _plain(result)
    assert "other" not in _plain(runner.invoke(app, ["store", "list"]))


def test_add_can_join_the_write_queue(project_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "queued").mkdir()
    (tmp_path / "homed").mkdir()

    queued = runner.invoke(
        app, ["store", "add", "queued", "--path", str(tmp_path / "queued"), "--queue"]
    )
    homed = runner.invoke(
        app, ["store", "add", "homed", "--path", str(tmp_path / "homed")]
    )

    assert queued.exit_code == 0 and "Added to the write queue" in _plain(queued)
    assert homed.exit_code == 0 and "store place set" in _plain(homed)
    from civex.config import load_config

    queue = load_config().store_config.volume_queue
    assert "queued" in queue and "homed" not in queue


def test_add_explains_a_network_address(project_dir: Path) -> None:
    result = runner.invoke(app, ["store", "add", "nas", "--path", "smb://nas/share"])

    assert result.exit_code == 1
    assert "mount it first" in _plain(result)


def test_where_shows_which_volume_each_file_is_on(
    project_dir: Path, tmp_path: Path
) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    assert runner.invoke(app, ["schema", "create", "doc"]).exit_code == 0
    assert (
        runner.invoke(
            app, ["schema", "add-field", "doc", "scan", "--type", "file"]
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["collection", "create", "study"]).exit_code == 0
    ctx = build_local_context(load_config())
    ref = ctx.file_svc.store_bytes(b"scan bytes", "scan.png")
    record = ctx.record_svc.add("study", "doc", {"scan": ref.to_dict()})
    ctx.commit()
    ctx.close()

    plain = runner.invoke(app, ["store", "where", str(record.id)])
    detailed = runner.invoke(app, ["store", "where", str(record.id), "--details"])

    assert plain.exit_code == 0, plain.output
    assert (
        "scan.png" in plain.output
        and "default" in plain.output
        and "online" in plain.output
    )
    assert detailed.exit_code == 0
    assert ref.sha256[:12] in detailed.output and "used by 1 record" in detailed.output
    assert runner.invoke(app, ["store", "where", "zzzzzzzz"]).exit_code == 1
