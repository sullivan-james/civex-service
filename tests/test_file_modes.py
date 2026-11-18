"""Read-only files civex can still remove and replace (`civex.file_modes`)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from civex import file_modes

_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root may write anything"
)


@_root
def test_a_read_only_file_cannot_be_saved_over(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("one")

    file_modes.make_read_only(f)

    assert not os.access(f, os.W_OK)
    with pytest.raises(PermissionError):
        f.write_text("two")


def test_a_read_only_file_can_still_be_removed_and_replaced(tmp_path: Path) -> None:
    gone, kept, new = tmp_path / "gone", tmp_path / "kept", tmp_path / "new"
    for f in (gone, kept, new):
        f.write_text(f.name)
        file_modes.make_read_only(f)

    file_modes.remove(gone)
    file_modes.replace(new, kept)

    assert not gone.exists() and kept.read_text() == "new"
    file_modes.remove(gone, missing_ok=True)
    with pytest.raises(FileNotFoundError):
        file_modes.remove(gone)


def test_a_file_whose_mode_cannot_change_is_left_alone(tmp_path: Path) -> None:
    file_modes.make_read_only(tmp_path / "not there")  # no error
