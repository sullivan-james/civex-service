"""A device may ask to join without an invite: it shows a short code, a
person approves it on the authority with a name, and the device, polling, is
told it joined, exactly as an invite would have told it. Denied or left too
long, it is told that instead."""

from __future__ import annotations

import pytest

from civex import keys, user_state
from civex.domain.exceptions import ValidationError
from civex.domain.sync import SyncError
from civex.services.device_keys import DeviceKeys

from civex.testing.peers import AsDevice, Loopback, connect, device, device_uuid


def _asking(authority, name: str = "laptop"):
    private = keys.new_private_key()
    started = authority.device_keys.request_login(
        device_uuid(name), keys.public_of(private)
    )
    authority.commit()
    return started, private


def test_a_person_approves_a_device_by_the_code_it_shows(authority):
    started, _ = _asking(authority)
    assert len(started.user_code) == 9 and started.user_code[4] == "-"
    assert started.interval >= 1
    assert authority.device_keys.poll_login(started.device_code) is None  # waiting
    [waiting] = authority.device_keys.pending_logins()
    assert waiting.user_code == started.user_code and waiting.name is None

    device = authority.device_keys.approve_login(started.user_code.lower(), "laptop")
    authority.commit()
    assert device.name == "laptop" and device.device_id == device_uuid("laptop")
    assert authority.device_keys.pending_logins() == []
    joined = authority.device_keys.poll_login(started.device_code)
    assert joined is not None and joined.device_name == "laptop"
    assert joined.authority_key == keys.public_of(authority.sync_repo.authority_key())
    # Asking again with the secret keeps answering the same.
    assert authority.device_keys.poll_login(started.device_code) is not None


def test_a_denied_or_expired_request_is_told_so_and_a_wrong_secret_gets_nothing(
    authority,
):
    started, _ = _asking(authority)
    assert authority.device_keys.deny_login(started.user_code) is True
    assert authority.device_keys.deny_login(started.user_code) is False  # gone
    with pytest.raises(SyncError, match="denied, or it expired") as e:
        authority.device_keys.poll_login(started.device_code)
    assert e.value.status == 410 and not e.value.retryable
    with pytest.raises(SyncError, match="no longer waiting"):
        authority.device_keys.poll_login("not-a-secret")

    late, _ = _asking(authority, "tablet")
    from datetime import datetime, timedelta, timezone

    from civex.db.models import SyncLoginRequest

    row = (
        authority._session.query(SyncLoginRequest)
        .filter_by(user_code=late.user_code)
        .one()
    )
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)  # time passes
    authority.commit()
    assert authority.device_keys.pending_logins() == []
    with pytest.raises(SyncError, match="expired"):
        authority.device_keys.poll_login(late.device_code)
    with pytest.raises(ValidationError, match="No device is waiting"):
        authority.device_keys.approve_login(late.user_code, "tablet")


def test_approving_checks_the_name_as_an_invite_would(authority):
    started, _ = _asking(authority, "laptop")
    other, _ = _asking(authority, "other")
    authority.device_keys.approve_login(started.user_code, "laptop")
    with pytest.raises(ValidationError, match="already follows"):
        authority.device_keys.approve_login(other.user_code, "laptop")
    with pytest.raises(ValidationError, match="needs a name"):
        authority.device_keys.approve_login(other.user_code, "  ")
    with pytest.raises(ValidationError, match="No device is waiting"):
        authority.device_keys.approve_login("ZZZZ-ZZZZ", "x")
    # The same machine asking again (connected afresh) replaces itself.
    again, _ = _asking(authority, "laptop")
    authority.device_keys.approve_login(again.user_code, "laptop")
    live = [d for d in authority.device_keys.list_devices() if not d.revoked_at]
    assert [d.name for d in live] == ["laptop"]


def test_a_device_connects_by_asking_and_waiting(project, authority):
    """The client's side: `connect` without an invite asks, shows the code,
    waits, and once approved joins and copies; connecting again later needs
    nothing, since this computer has joined that address."""
    from civex.testing.peers import build_study

    build_study(authority)
    laptop = device(project, authority, "laptop")
    svc = object.__getattribute__(laptop.sync_svc, "_svc")
    shown: list[str] = []

    def approve(started) -> None:  # the person, reading the code off the laptop
        shown.append(started.user_code)
        authority.device_keys.approve_login(started.user_code, "laptop")
        authority.commit()

    svc._sleep = lambda _s: None
    assert laptop.sync_svc.connect("https://authority.test", None, on_code=approve) == (
        "joined"
    )
    laptop.commit()
    assert len(shown) == 1
    assert laptop.record_svc.find("study", "encounter", limit=10)
    assert "laptop" in [d.name for d in authority.device_keys.list_devices()]
    # Joined once: a later connect needs neither invite nor approval.
    assert connect(laptop) == "resumed"


def test_a_device_waiting_too_long_gives_up_with_a_plain_reason(project, authority):
    laptop = device(project, authority, "laptop")
    svc = object.__getattribute__(laptop.sync_svc, "_svc")
    svc._sleep = lambda _s: None
    told: list[str] = []

    def deny(started) -> None:
        told.append(started.user_code)
        authority.device_keys.deny_login(started.user_code)
        authority.commit()

    with pytest.raises(SyncError, match="denied, or it expired"):
        laptop.sync_svc.connect("https://authority.test", None, on_code=deny)
    assert told
    with pytest.raises(SyncError, match="ask its admin for an invite"):
        laptop.sync_svc.connect("https://authority.test", None)


def test_the_app_asks_first_and_waits_in_the_background(project, authority):
    """What the app does: `needs_approval` then `request_login` at once (the
    code goes on screen), and the connect, given the request, waits on it."""
    laptop = device(project, authority, "laptop")
    svc = object.__getattribute__(laptop.sync_svc, "_svc")
    svc._sleep = lambda _s: None
    assert laptop.sync_svc.needs_approval("https://authority.test", None)
    assert not laptop.sync_svc.needs_approval("https://authority.test", "civex_inv_x")
    started = laptop.sync_svc.request_login("https://authority.test")
    assert [r.user_code for r in authority.device_keys.pending_logins()] == [
        started.user_code
    ]
    authority.device_keys.approve_login(started.user_code, "laptop")
    authority.commit()
    assert (
        laptop.sync_svc.connect("https://authority.test", None, login=started)
        == "empty"
    )
    assert not laptop.sync_svc.needs_approval("https://authority.test", None)


def _unused(*_: object) -> None:  # keep the imports honest for ruff
    DeviceKeys, Loopback, AsDevice, user_state
