"""Who may follow an authority: a device it invited, signing in with a key that
never leaves it. Nothing a device sends can be reused for long, and nothing is
written on the authority without an invite."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from civex import keys
from civex.db.models import SyncInvite
from civex.domain.sync import (
    CLOCK_SKEW_SECONDS,
    SyncError,
    session_answer,
    session_request,
)
from civex.services.device_keys import DeviceKeys

from .peers import build_study, connect, device


def _device() -> tuple[str, str]:
    """(device id, private key) of a new machine."""
    return str(uuid.uuid4()), keys.new_private_key()


def _join(authority, invite: str, who: tuple[str, str]):
    joined = authority.device_keys.join(invite, who[0], keys.public_of(who[1]))
    authority.commit()
    return joined


def _sign_in(authority, who: tuple[str, str], at: int | None = None):
    """(grant, the device's signature) for a sign-in at `at` (now)."""
    at = int(time.time()) if at is None else at
    authority_key = keys.public_of(authority.sync_repo.authority_key())
    signature = keys.sign(who[1], session_request(authority_key, who[0], at))
    return authority.device_keys.start_session(who[0], at, signature), signature


def test_an_invite_works_once(authority):
    _, invite = authority.device_keys.invite("laptop")
    assert invite.startswith("civex_inv_")  # recognisable by secret scanners
    _join(authority, invite, _device())
    with pytest.raises(SyncError, match="used already"):
        _join(authority, invite, _device())
    assert [d.name for d in authority.device_keys.list_devices()] == ["laptop"]


def test_an_expired_or_cancelled_invite_is_refused(authority):
    keys_svc: DeviceKeys = authority.device_keys
    _, cancelled = keys_svc.invite("phone")
    assert keys_svc.cancel_invite("phone") is True
    with pytest.raises(SyncError, match="cancelled"):
        _join(authority, cancelled, _device())

    found, invite = keys_svc.invite("tablet", hours=1)
    row = authority.sync_repo._s.get(SyncInvite, found.id)
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(SyncError, match="expired"):
        _join(authority, invite, _device())


def test_a_wrong_invite_writes_nothing(authority):
    with pytest.raises(SyncError):
        _join(authority, "civex_inv_guess", _device())
    assert authority.device_keys.list_devices() == []
    assert authority.sync_repo.authority_key() is None


def test_one_name_one_device_and_one_waiting_invite(authority):
    authority.device_keys.invite("laptop")
    with pytest.raises(Exception, match="already has an invite"):
        authority.device_keys.invite("laptop")


def test_a_device_signs_in_with_its_key_and_its_session_names_it(authority):
    who = _device()
    _, invite = authority.device_keys.invite("laptop")
    joined = _join(authority, invite, who)
    grant, signature = _sign_in(authority, who)
    # The authority signed its answer to this very request, with the key the
    # device was given when it joined.
    assert keys.verifies(
        joined.authority_key, session_answer(signature), grant.signature
    )
    principal = authority.device_keys.authenticate(grant.token)
    assert (principal.name, principal.device_id) == ("laptop", who[0])


def test_signing_in_with_another_key_or_a_wrong_clock_is_refused(authority):
    who = _device()
    _, invite = authority.device_keys.invite("laptop")
    _join(authority, invite, who)
    with pytest.raises(SyncError, match="key this computer joined with"):
        _sign_in(authority, (who[0], keys.new_private_key()))
    with pytest.raises(SyncError, match="clock"):
        _sign_in(authority, who, at=int(time.time()) - CLOCK_SKEW_SECONDS - 60)
    with pytest.raises(SyncError, match="never joined"):
        _sign_in(authority, _device())


def test_a_session_token_can_not_be_forged_or_used_after_it_expires(
    authority, monkeypatch
):
    who = _device()
    _, invite = authority.device_keys.invite("laptop")
    _join(authority, invite, who)
    token = _sign_in(authority, who)[0].token
    row, expires, mac = token.split(".")
    with pytest.raises(SyncError):
        authority.device_keys.authenticate(f"{row}.{int(expires) + 3600}.{mac}")
    with pytest.raises(SyncError):
        authority.device_keys.authenticate("not-a-token")
    monkeypatch.setattr(
        "civex.services.device_keys.time.time", lambda: int(expires) + 1
    )
    with pytest.raises(SyncError, match="expired"):
        authority.device_keys.authenticate(token)


def test_revoking_a_device_stops_it_at_once(project, authority):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    connect(laptop)
    authority.device_keys.revoke_device("laptop")
    authority.commit()
    with pytest.raises(SyncError, match="revoked") as raised:
        laptop.sync_svc.sync()  # its session was still young
    assert raised.value.retryable is False


def test_a_device_joins_once_and_connects_again_without_an_invite(project, authority):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    assert connect(laptop) == "seeded"
    laptop.sync_svc.disconnect()
    with pytest.raises(SyncError, match="invite"):
        laptop.sync_svc.connect("https://authority.test", None)
    # Invited again (say after a disconnect), the same machine replaces itself.
    _, again = authority.device_keys.invite("laptop-2")
    authority.commit()
    assert laptop.sync_svc.connect("https://authority.test", again) == "resumed"
    live = [d.name for d in authority.device_keys.list_devices() if not d.revoked_at]
    assert live == ["laptop-2"]
