"""Filesystem helpers for the volume pickers: listing folders, finding drives
(network ones included), and the time limit that keeps a dead mount from
freezing a request."""

from __future__ import annotations

import threading
import time
import types
from pathlib import Path

import sys

import pytest

from civex import fs_locations as fs
from civex.fs_locations import Mount


def test_normalise_expands_home_and_dots_and_backslashes(tmp_path: Path) -> None:
    assert fs.normalise("~") == Path.home().as_posix()
    assert fs.normalise(str(tmp_path / "a" / ".." / "b")) == (tmp_path / "b").as_posix()
    assert "\\" not in fs.normalise("a\\b")  # forward slashes only


def test_list_subdirectories_returns_only_folders_sorted_and_skips_hidden(
    tmp_path: Path,
) -> None:
    for name in ("beta", "Alpha", ".hidden", "gamma"):
        (tmp_path / name).mkdir()
    (tmp_path / "a-file.txt").write_text("x")

    entries, truncated = fs.list_subdirectories(str(tmp_path))
    assert [n for n, _ in entries] == ["Alpha", "beta", "gamma"]
    assert truncated is False
    shown, _ = fs.list_subdirectories(str(tmp_path), show_hidden=True)
    assert ".hidden" in [n for n, _ in shown]
    assert entries[0][1] == (tmp_path / "Alpha").as_posix()


def test_list_subdirectories_truncates(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"d{i}").mkdir()
    entries, truncated = fs.list_subdirectories(str(tmp_path), limit=3)
    assert len(entries) == 3 and truncated is True


def test_list_subdirectories_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fs.list_subdirectories(str(tmp_path / "nope"))
    (tmp_path / "f").write_text("x")
    with pytest.raises(NotADirectoryError):
        fs.list_subdirectories(str(tmp_path / "f"))


def test_disk_usage_of_a_folder_that_does_not_exist_yet(tmp_path: Path) -> None:
    free, total = fs.disk_usage(str(tmp_path / "not" / "there" / "yet"))
    assert free is not None and total is not None


# -- network ------------------------------------------------------------------


def test_network_addresses_are_recognised() -> None:
    for addr in ("smb://nas/share", "NFS://nas/x", "sftp://h/p", "https://x/y"):
        assert fs.looks_like_network_address(addr), addr
    # `//host/share` is a UNC path, a valid local path, on Windows.
    assert fs.looks_like_network_address("//nas/share") == (sys.platform != "win32")
    for path in ("/mnt/nas", "relative/dir", "/home/me", "C:/data"):
        assert not fs.looks_like_network_address(path), path


MOUNTS = [
    Mount("/dev/sdb1", "/", "ext4"),
    Mount("nas:/export", "/mnt/nas", "nfs4"),
    Mount("//nas/media", "/mnt/media", "cifs"),
    Mount("/dev/sdc1", "/mnt/nas/local", "ext4"),
    Mount("/dev/sdd1", "/media/me/USB STICK", "vfat"),
    Mount("tmpfs", "/run/user/1000", "tmpfs"),
    Mount("proc", "/proc", "proc"),
]


# POSIX mount tables are only consulted on POSIX; Windows asks the drive type.
@pytest.mark.posix_only
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mount table")
def test_is_network_path_uses_the_innermost_mount() -> None:
    assert fs.is_network_path("/mnt/nas/backups/2026", MOUNTS)
    assert fs.is_network_path("/mnt/media", MOUNTS)
    assert not fs.is_network_path(
        "/mnt/nas/local/data", MOUNTS
    )  # a local disk mounted inside
    assert not fs.is_network_path("/home/me", MOUNTS)
    assert not fs.is_network_path("/mnt/nasty", MOUNTS)  # a prefix isn't a parent


def test_mounted_drives_lists_real_drives_and_marks_network_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs, "all_mounts", lambda: MOUNTS)
    monkeypatch.setattr(fs.sys, "platform", "linux")

    drives = {d.path: d for d in fs.mounted_drives()}

    assert set(drives) == {
        "/mnt/nas",
        "/mnt/media",
        "/mnt/nas/local",
        "/media/me/USB STICK",
    }
    assert drives["/mnt/nas"].network and drives["/mnt/nas"].source == "nas:/export"
    assert not drives["/media/me/USB STICK"].network
    assert drives["/media/me/USB STICK"].source is None


def test_linux_mount_table_parsing(tmp_path: Path) -> None:
    table = tmp_path / "mounts"
    table.write_text(
        "nas:/ex /mnt/my\\040nas nfs4 rw 0 0\n/dev/sda1 / ext4 rw 0 0\nbroken\n"
    )
    mounts = fs._linux_mounts(str(table))
    assert mounts == [
        Mount("nas:/ex", "/mnt/my nas", "nfs4"),
        Mount("/dev/sda1", "/", "ext4"),
    ]


def test_macos_mount_output_parsing() -> None:
    mounts = fs._macos_mounts(
        "//guest@nas._smb._tcp.local/share on /Volumes/share (smbfs, nodev, nosuid)\n"
        "/dev/disk3s1 on / (apfs, local, journaled)\n"
    )
    assert mounts[0] == Mount(
        "//guest@nas._smb._tcp.local/share", "/Volumes/share", "smbfs"
    )
    assert mounts[0].network and not mounts[1].network


# -- the time limit -----------------------------------------------------------


@pytest.fixture()
def short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "FS_TIMEOUT", 0.2)


def test_guarded_returns_results_and_passes_exceptions_through(
    short_timeout: None,
) -> None:
    assert fs.guarded("t-ok", lambda a, b=0: a + b, 1, b=2) == 3
    with pytest.raises(FileNotFoundError):
        fs.guarded("t-err", lambda: Path("/definitely/not/here").stat())


def test_a_call_that_never_returns_is_reported_not_waited_on(
    short_timeout: None,
) -> None:
    release = threading.Event()
    try:
        started = time.monotonic()
        with pytest.raises(fs.Unresponsive, match="no answer"):
            fs.guarded("t-hang", release.wait, 30)
        assert time.monotonic() - started < 2

        # While that call is still stuck, the next one fails at once rather
        # than queueing another blocked thread behind the dead mount.
        started = time.monotonic()
        with pytest.raises(fs.Unresponsive, match="still waiting"):
            fs.guarded("t-hang", lambda: "never runs")
        assert time.monotonic() - started < 0.1

        # Other locations are unaffected.
        assert fs.guarded("t-other", lambda: "fine") == "fine"
    finally:
        release.set()

    time.sleep(0.2)  # the stuck call has now returned: the location works again
    assert fs.guarded("t-hang", lambda: "recovered") == "recovered"


def test_a_call_a_caller_gave_up_on_counts_as_stuck_whatever_the_clock_says(
    short_timeout: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The caller that gives up on a call measures its time from before the call
    # was submitted, so it can give up a hair before the call is FS_TIMEOUT old
    # by the call's own clock -- on a coarse clock (Windows), by enough that the
    # next caller used to judge the location merely busy and wait its own full
    # timeout. A call someone has already given up on is stuck, by definition.
    # The clock is frozen here to make that the case every time, not by chance.
    frozen = types.SimpleNamespace(monotonic=lambda: 100.0)
    monkeypatch.setattr(fs, "time", frozen)
    release = threading.Event()
    try:
        with pytest.raises(fs.Unresponsive, match="no answer"):
            fs.guarded("t-frozen", release.wait, 30)

        started = time.monotonic()  # the real clock, for how long this takes
        with pytest.raises(fs.Unresponsive, match="still waiting"):
            fs.guarded("t-frozen", lambda: "never runs")
        assert time.monotonic() - started < 0.1
    finally:
        release.set()


def test_concurrent_callers_on_a_busy_but_healthy_location_all_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A slow-but-answering mount (a copy running, several requests probing at
    # once) must not read as "not responding" to the callers that arrive while
    # an earlier probe is still in flight.
    monkeypatch.setattr(fs, "FS_TIMEOUT", 2.0)
    runs: list[int] = []

    def probe(x: int) -> int:
        runs.append(x)
        time.sleep(0.3)
        return x

    results: list[object] = []

    def call(x: int) -> None:
        try:
            results.append(fs.guarded("t-busy", probe, x))
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=call, args=(1,)) for _ in range(4)]
    threads += [threading.Thread(target=call, args=(2,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [1, 1, 1, 1, 2, 2]  # type: ignore[type-var]
    assert runs.count(1) == 1  # identical concurrent calls share one run


def test_a_different_call_waits_its_turn_behind_a_young_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs, "FS_TIMEOUT", 2.0)
    order: list[str] = []

    def first() -> str:
        time.sleep(0.3)
        order.append("first")
        return "a"

    got: list[str] = []
    t = threading.Thread(target=lambda: got.append(fs.guarded("t-turn", first)))
    t.start()
    time.sleep(0.05)
    assert fs.guarded("t-turn", lambda: order.append("second") or "b") == "b"
    t.join()
    assert order == ["first", "second"]


def test_platform_hint_explains_missing_drives_under_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fs, "_proc_version", lambda: "Linux version 6.6.1-microsoft-standard-WSL2"
    )
    hint = fs.platform_hint()
    assert hint is not None and "drvfs" in hint and "rescan" in hint

    monkeypatch.setattr(fs, "_proc_version", lambda: "Linux version 6.8.0-generic")
    assert fs.platform_hint() is None
    monkeypatch.setattr(fs, "_proc_version", lambda: "")
    assert fs.platform_hint() is None
