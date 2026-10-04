"""Choosing where a volume lives: browsing folders, checking a path before it
is added, network drives, and a dead mount not freezing everything."""

from __future__ import annotations

import os
import sys
import shutil
import threading
import time
from pathlib import Path

import pytest

from civex import fs_locations
from civex.config import StoreConfig, VolumeConfig
from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.repositories.local import file_store as file_store_module
from civex.repositories.local.file_store import VolumeAwareFileObjectStore


def _drive(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "mnt" / name
    path.mkdir(parents=True)
    return path


@pytest.fixture()
def short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs_locations, "FS_TIMEOUT", 0.3)


# -- browsing -----------------------------------------------------------------


def test_browse_lists_folders_with_a_parent_and_places_to_start(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path = tmp_path / "pick"  # the project dir itself holds _civex
    tmp_path.mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "file.txt").write_text("x")
    monkeypatch.setattr(
        fs_locations,
        "mounted_drives",
        lambda: [
            fs_locations.Drive("usb", "/media/usb"),
            fs_locations.Drive("nas", "/mnt/nas", network=True, source="nas:/export"),
        ],
    )

    listing = ctx.store_svc.browse_directory(str(tmp_path))

    assert listing.path == str(tmp_path)
    assert listing.parent == str(tmp_path.parent)
    assert [e.name for e in listing.entries] == ["a", "b"]
    kinds = {loc.label: loc for loc in listing.locations}
    assert {"Project", "Home", "usb", "nas"} <= set(kinds)
    assert kinds["nas"].network and kinds["nas"].source == "nas:/export"
    assert kinds["nas"].free_bytes is None  # not read for network drives
    assert kinds["Home"].free_bytes is not None


def test_browse_at_the_top_has_no_parent(ctx: AppContext) -> None:
    assert ctx.store_svc.browse_directory("/").parent is None


def test_browse_errors_are_clear(ctx: AppContext, tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x")
    with pytest.raises(NotFoundError, match="not found"):
        ctx.store_svc.browse_directory(str(tmp_path / "nope"))
    with pytest.raises(ValidationError, match="not a folder"):
        ctx.store_svc.browse_directory(str(tmp_path / "f"))
    with pytest.raises(ValidationError, match="mount it first"):
        ctx.store_svc.browse_directory("smb://nas/share")


def test_browsing_a_location_that_stops_answering_reports_it(
    ctx: AppContext,
    tmp_path: Path,
    short_timeout: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    monkeypatch.setattr(
        fs_locations, "list_subdirectories", lambda *a, **k: release.wait(30)
    )
    try:
        started = time.monotonic()
        with pytest.raises(ValidationError, match="isn't responding"):
            ctx.store_svc.browse_directory(str(tmp_path))
        assert time.monotonic() - started < 3
    finally:
        release.set()


def test_create_folder(ctx: AppContext, tmp_path: Path) -> None:
    made = ctx.store_svc.create_folder(str(tmp_path), "civex-data")
    assert Path(made).is_dir() and made == str(tmp_path / "civex-data")
    with pytest.raises(AlreadyExistsError):
        ctx.store_svc.create_folder(str(tmp_path), "civex-data")
    with pytest.raises(NotFoundError):
        ctx.store_svc.create_folder(str(tmp_path / "missing"), "x")
    for bad in ("", ".", "..", "a/b", "a\\b"):
        with pytest.raises(ValidationError, match="slashes"):
            ctx.store_svc.create_folder(str(tmp_path), bad)


# -- inspecting a path before adding it ---------------------------------------


def test_inspecting_a_new_folder_warns_that_it_will_be_created(
    ctx: AppContext, tmp_path: Path
) -> None:
    inspection = ctx.store_svc.inspect_path(str(tmp_path / "mnt" / "usb" / "civex"))

    assert inspection.problems == []
    assert inspection.will_create and not inspection.exists
    assert any("will create it" in w and "connected" in w for w in inspection.warnings)
    assert inspection.free_bytes and inspection.total_bytes


def test_inspecting_an_existing_writable_folder_is_clean(
    ctx: AppContext, tmp_path: Path
) -> None:
    inspection = ctx.store_svc.inspect_path(str(_drive(tmp_path, "ok")))

    assert inspection.problems == [] and inspection.exists and inspection.is_dir
    assert inspection.writable and not inspection.will_create
    assert not inspection.is_network


def test_a_file_is_not_a_folder(ctx: AppContext, tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x")

    assert any(
        "is a file" in p for p in ctx.store_svc.inspect_path(str(target)).problems
    )


@pytest.mark.posix_only
@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="needs POSIX permissions, and root can write anywhere",
)
def test_a_folder_civex_cannot_write_to_is_a_problem(
    ctx: AppContext, tmp_path: Path
) -> None:
    locked = _drive(tmp_path, "locked")
    locked.chmod(0o500)
    try:
        problems = ctx.store_svc.inspect_path(str(locked)).problems
    finally:
        locked.chmod(0o700)
    assert any("can't write" in p for p in problems)


def test_a_folder_that_is_already_a_volume_is_refused(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "usb")
    ctx.store_svc.add_volume("usb", str(drive))

    inspection = ctx.store_svc.inspect_path(str(drive))
    assert inspection.existing_volume == "usb"
    assert "already the volume 'usb'" in inspection.problems[0]
    with pytest.raises(ValidationError, match="already the volume 'usb'"):
        ctx.store_svc.add_volume("again", str(drive))


def test_another_volumes_drive_at_a_different_path_is_refused(
    ctx: AppContext, tmp_path: Path
) -> None:
    first = _drive(tmp_path, "usb")
    ctx.store_svc.add_volume("usb", str(first))
    remounted = _drive(tmp_path, "usb-elsewhere")
    shutil.copy(first / ".civex-volume", remounted / ".civex-volume")

    inspection = ctx.store_svc.inspect_path(str(remounted))
    assert inspection.marker_volume == "usb"
    assert "drive of volume 'usb'" in inspection.problems[0]
    with pytest.raises(ValidationError, match="drive of volume 'usb'"):
        ctx.store_svc.add_volume("other", str(remounted))
    assert "other" not in ctx.store_svc._config.store_config.volumes


def test_a_folder_that_already_holds_civex_files_is_noted(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "old")
    (drive / "ab").mkdir()
    (drive / "manifest.jsonl").write_text("")

    inspection = ctx.store_svc.inspect_path(str(drive))
    assert inspection.has_civex_data
    assert any("already holds Civex files" in w for w in inspection.warnings)


def test_inspection_matches_what_add_volume_does(
    ctx: AppContext, tmp_path: Path
) -> None:
    """The preview and the action share one rule set."""
    target = tmp_path / "file.txt"
    target.write_text("x")
    assert ctx.store_svc.inspect_path(str(target)).problems
    with pytest.raises(ValidationError):
        ctx.store_svc.add_volume("f", str(target))


# -- network drives -----------------------------------------------------------


def test_a_network_location_is_flagged_with_what_that_means(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fs_locations, "is_network_path", lambda path, mounts=None: True)

    inspection = ctx.store_svc.inspect_path(str(_drive(tmp_path, "nas")))

    assert inspection.is_network and inspection.problems == []
    assert any("network location" in w and "offline" in w for w in inspection.warnings)
    assert not any("same disk" in w for w in inspection.warnings)


def test_a_network_address_must_be_mounted_first(ctx: AppContext) -> None:
    for address in ("smb://nas/share", "//nas/share", "nfs://nas/export"):
        inspection = ctx.store_svc.inspect_path(address)
        assert "mount it first" in inspection.problems[0], address
        with pytest.raises(ValidationError, match="mount it first"):
            ctx.store_svc.add_volume("nas", address)


def test_inspecting_a_location_that_stops_answering_blocks_the_add(
    ctx: AppContext,
    tmp_path: Path,
    short_timeout: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    monkeypatch.setattr(
        "civex.services.store_service._fs_facts", lambda *a: release.wait(30)
    )
    try:
        inspection = ctx.store_svc.inspect_path(str(tmp_path / "dead"))
        assert "isn't responding" in inspection.problems[0]
    finally:
        release.set()


# -- add_volume options -------------------------------------------------------


def test_add_volume_can_join_the_write_queue_or_stay_out(
    ctx: AppContext, tmp_path: Path
) -> None:
    ctx.store_svc.add_volume("scratch", str(_drive(tmp_path, "scratch")))
    ctx.store_svc.add_volume("main", str(_drive(tmp_path, "main")), add_to_queue=True)

    queue = ctx.store_svc._config.store_config.volume_queue
    assert "main" in queue and "scratch" not in queue
    from civex.config import load_config

    assert load_config().store_config.volume_queue == queue


# -- a dead mount must not stall everything -----------------------------------


@pytest.fixture()
def hung_drive(tmp_path: Path, short_timeout: None, monkeypatch: pytest.MonkeyPatch):
    """A store whose first volume (outside the project) never answers, then a
    healthy local one."""
    release = threading.Event()
    dead = _drive(tmp_path, "dead")
    real_probe = file_store_module._probe_root

    def probe(root: Path):
        if root == dead:
            release.wait(30)
        return real_probe(root)

    monkeypatch.setattr(file_store_module, "_probe_root", probe)
    config = StoreConfig(
        volumes={
            "dead": VolumeConfig(name="dead", path=str(dead)),
            "local": VolumeConfig(name="local", path="objects"),
        },
        volume_queue=["dead", "local"],
    )
    store = VolumeAwareFileObjectStore(config, tmp_path)
    yield store
    release.set()


def test_a_volume_that_stops_answering_is_offline_with_a_reason(hung_drive) -> None:
    started = time.monotonic()
    status = hung_drive.volume_status("dead")

    assert status.state == "offline" and "not responding" in status.reason
    assert "network connection" in status.fix
    assert time.monotonic() - started < 3


def test_writes_go_to_the_next_volume_when_one_stops_answering(hung_drive) -> None:
    assert hung_drive.put(b"still works", "a.txt").volume == "local"


def test_reads_of_other_volumes_are_not_stalled_by_a_dead_one(hung_drive) -> None:
    ref = hung_drive.put(b"findable", "a.txt")

    started = time.monotonic()
    assert hung_drive.get(ref.sha256) == b"findable"
    assert hung_drive.exists(ref.sha256)
    assert time.monotonic() - started < 2
    # The second look doesn't wait again: the stuck probe is remembered.
    started = time.monotonic()
    hung_drive.get(ref.sha256)
    assert time.monotonic() - started < 0.5


def test_volume_stats_flags_network_volumes(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = _drive(tmp_path, "nas")
    ctx.store_svc.add_volume("nas", str(nas))
    monkeypatch.setattr(
        fs_locations,
        "all_mounts",
        lambda: [fs_locations.Mount("nas:/export", str(nas), "nfs4")],
    )

    stats = {v["name"]: v for v in ctx.store_svc.volume_stats()}

    assert stats["nas"]["network"] is True
    assert stats["default"]["network"] is False


# -- config.toml is written atomically ---------------------------------------


def test_a_reader_never_sees_the_config_half_written(ctx: AppContext) -> None:
    """Every request reads config.toml, and a transfer rewrites it while it
    freezes a volume: a reader must get the old file or the new one."""
    from civex.config import load_config, save_config

    config = load_config()
    stop = threading.Event()
    failures: list[BaseException] = []

    def write() -> None:
        flip = False
        while not stop.is_set():
            config.store_config.warn_below_pct = 11.0 if flip else 12.0
            flip = not flip
            try:
                save_config(config)
            except BaseException as e:  # noqa: BLE001
                failures.append(e)
                return

    writer = threading.Thread(target=write)
    writer.start()
    try:
        for _ in range(400):
            load_config()  # raised KeyError('db') on a half-written file before
    finally:
        stop.set()
        writer.join()

    assert not failures


def test_a_failed_config_write_leaves_the_original_untouched(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from civex.config import load_config, save_config
    from civex.domain.exceptions import ConfigError

    config = load_config()
    path = config.civex_dir / "config.toml"
    before = path.read_text()
    monkeypatch.setattr(
        os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )

    with pytest.raises(ConfigError, match="original is untouched"):
        save_config(config)

    assert path.read_text() == before
    assert not list(path.parent.glob("config.toml.*.tmp"))  # no litter left behind
