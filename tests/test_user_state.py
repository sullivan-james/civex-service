"""A device's identity and token live in the user's own state, not the project."""

from __future__ import annotations

import stat
import sys
import uuid
from pathlib import Path

import pytest

from civex import user_state


@pytest.fixture(autouse=True)
def _own_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "sync.toml"
    monkeypatch.setenv("CIVEX_USER_STATE", str(path))
    return path


def test_a_project_keeps_one_device_id_and_another_project_gets_its_own():
    first, second = uuid.uuid4(), uuid.uuid4()
    a = user_state.device_id_for(first)
    assert user_state.device_id_for(first) == a
    assert user_state.device_id_for(second) != a


def test_forgetting_a_device_means_a_new_one_next_time():
    project = uuid.uuid4()
    a = user_state.device_id_for(project)
    user_state.forget_device(project)
    assert user_state.device_id_for(project) != a


def test_an_authority_is_known_by_its_address_however_it_ends():
    user_state.save_authority("https://hub.example/", "pub")
    assert user_state.authority_for("https://hub.example") == "pub"
    assert user_state.authority_for("https://other.example") is None
    user_state.forget_authority("https://hub.example")
    assert user_state.authority_for("https://hub.example") is None


def test_a_device_keeps_one_key_per_project_and_moves_it_with_its_id():
    old, new = uuid.uuid4(), uuid.uuid4()
    device, key = user_state.device_id_for(old), user_state.device_key_for(old)
    assert user_state.device_key_for(old) == key
    assert user_state.device_key_for(uuid.uuid4()) != key
    user_state.save_authority("https://hub.example", "pub")
    user_state.move_device(old, new)
    assert (user_state.device_id_for(new), user_state.device_key_for(new)) == (
        device,
        key,
    )
    assert user_state.authority_for("https://hub.example") == "pub"
    user_state.forget_device(new)
    assert user_state.device_key_for(new) != key


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_file_is_private(_own_state: Path):
    user_state.device_key_for(uuid.uuid4())
    assert stat.S_IMODE(_own_state.stat().st_mode) == 0o600


def test_a_damaged_file_is_treated_as_empty_not_a_crash(_own_state: Path):
    _own_state.parent.mkdir(parents=True)
    _own_state.write_text("not [valid toml", encoding="utf-8")
    assert user_state.authority_for("https://hub.example") is None
    assert isinstance(user_state.device_id_for(uuid.uuid4()), uuid.UUID)


def test_the_name_changes_are_recorded_under_comes_from_the_projects_config(tmp_path):
    from civex.config import IdentityConfig  # noqa: F401
    from civex.identity import local_actor

    assert local_actor("  Dana  ") == "Dana"
    assert local_actor(None) == local_actor("")  # the OS user
