"""SQLite URLs and file paths convert both ways, whatever the OS."""

from __future__ import annotations

from pathlib import Path

from civex.db.sqlite_url import sqlite_file, sqlite_url


def test_a_path_round_trips_through_its_url(tmp_path: Path) -> None:
    path = tmp_path / "moved.db"
    assert sqlite_file(sqlite_url(path)) == path


def test_a_windows_drive_letter_is_not_read_as_a_directory() -> None:
    # urlparse(...).path would give '/C:/Users/me/civex.db', which Windows rejects.
    assert sqlite_file("sqlite:///C:/Users/me/civex.db").as_posix() == (
        "C:/Users/me/civex.db"
    )


def test_a_posix_absolute_path() -> None:
    assert sqlite_file("sqlite:////home/me/civex.db").as_posix() == "/home/me/civex.db"
