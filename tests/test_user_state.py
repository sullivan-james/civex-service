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


def test_a_token_is_found_by_the_remote_however_its_address_ends():
    user_state.save_token("https://hub.example/", "s3cret")
    assert user_state.token_for("https://hub.example") == "s3cret"
    assert user_state.token_for("https://other.example") is None
    user_state.forget_token("https://hub.example")
    assert user_state.token_for("https://hub.example") is None


def test_tokens_and_devices_do_not_disturb_each_other():
    project = uuid.uuid4()
    user_state.save_token("https://hub.example", "t")
    device = user_state.device_id_for(project)
    user_state.save_token("https://hub.example", "t2")
    assert user_state.device_id_for(project) == device
    assert user_state.token_for("https://hub.example") == "t2"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_file_is_private(_own_state: Path):
    user_state.save_token("https://hub.example", "t")
    assert stat.S_IMODE(_own_state.stat().st_mode) == 0o600


def test_a_damaged_file_is_treated_as_empty_not_a_crash(_own_state: Path):
    _own_state.parent.mkdir(parents=True)
    _own_state.write_text("not [valid toml", encoding="utf-8")
    assert user_state.token_for("https://hub.example") is None
    assert isinstance(user_state.device_id_for(uuid.uuid4()), uuid.UUID)


def test_a_chosen_name_is_per_project_and_can_be_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("CIVEX_USER_STATE", str(tmp_path / "s.toml"))
    from civex import user_state
    from civex.identity import local_actor

    one, two = (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    assert user_state.actor_for(one) is None
    user_state.set_actor(one, "  Dana  ")
    assert local_actor(one) == "Dana"
    assert (
        local_actor(two) == local_actor()
    )  # the OS user: another project is unaffected
    user_state.set_actor(one, "")
    assert user_state.actor_for(one) is None
