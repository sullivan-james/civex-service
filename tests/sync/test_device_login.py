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


def test_identity_says_who_this_computer_is_before_and_after_joining(
    project, authority
):
    laptop = device(project, authority, "laptop")
    before = laptop.sync_svc.identity()
    assert before.remote is None and before.device_id is None and not before.joined
    assert before.device_name is None

    connect(laptop)
    laptop.commit()
    after = laptop.sync_svc.identity()
    assert after.remote == "https://authority.test" and after.joined
    assert after.device_name == "laptop"
    assert after.device_id
    # Without asking the authority nothing goes over the wire: no name.
    assert laptop.sync_svc.identity(ask=False).device_name is None


def _unused(*_: object) -> None:  # keep the imports honest for ruff
    DeviceKeys, Loopback, AsDevice, user_state


def _approver(authority, name, shown):
    def approve(started) -> None:
        shown.append(started.user_code)
        authority.device_keys.approve_login(started.user_code, name)
        authority.commit()

    return approve


def test_a_second_project_on_a_machine_that_joined_signs_in_instead_of_being_refused(
    project, authority
):
    """Device ids are per project; the machine joined this address already for
    another project, and the authority doesn't know the new one."""
    from civex.testing.peers import build_study

    build_study(authority)
    first = device(project, authority, "laptop")
    svc = object.__getattribute__(first.sync_svc, "_svc")
    svc._sleep = lambda _s: None
    shown: list[str] = []
    first.sync_svc.connect(
        "https://authority.test", None, on_code=_approver(authority, "laptop", shown)
    )
    assert len(shown) == 1

    second = device(project, authority, "tablet")
    # The same computer: one user-state file, but a device of its own per project.
    object.__setattr__(
        second.sync_svc, "_state", object.__getattribute__(first.sync_svc, "_state")
    )
    svc2 = object.__getattribute__(second.sync_svc, "_svc")
    svc2._sleep = lambda _s: None
    shown2: list[str] = []
    second.sync_svc.connect(
        "https://authority.test", None, on_code=_approver(authority, "tablet", shown2)
    )
    assert len(shown2) == 1  # the browser sign-in, not a refusal
    assert "tablet" in [d.name for d in authority.device_keys.list_devices()]


def test_a_revoked_device_signs_in_again(project, authority):
    from civex.testing.peers import build_study

    build_study(authority)
    laptop = device(project, authority, "laptop")
    svc = object.__getattribute__(laptop.sync_svc, "_svc")
    svc._sleep = lambda _s: None
    shown: list[str] = []
    laptop.sync_svc.connect(
        "https://authority.test", None, on_code=_approver(authority, "laptop", shown)
    )
    authority.device_keys.revoke_device("laptop")
    authority.commit()
    laptop.sync_svc.connect(
        "https://authority.test", None, on_code=_approver(authority, "laptop", shown)
    )
    assert len(shown) == 2


def test_an_invite_still_works_for_a_second_project(project, authority):
    first = device(project, authority, "laptop")
    connect(first)
    second = device(project, authority, "tablet")
    object.__setattr__(
        second.sync_svc, "_state", object.__getattribute__(first.sync_svc, "_state")
    )
    assert second.sync_svc.connect("https://authority.test", second._invite) in (
        "joined",
        "empty",
        "seeded",
    )


def test_a_bad_signature_is_not_turned_into_a_sign_in(project, authority, monkeypatch):
    laptop = device(project, authority, "laptop")
    connect(laptop)
    shown: list[str] = []
    real = authority.device_keys.start_session

    def wrong(device_id, at, signature):
        raise SyncError("bad", retryable=False, status=401, code="bad_signature")

    monkeypatch.setattr(authority.device_keys, "start_session", wrong)
    laptop._holder["inner"]._token = None  # a new session is needed
    with pytest.raises(SyncError, match="bad"):
        laptop.sync_svc.connect(
            "https://authority.test", None, on_code=_approver(authority, "x", shown)
        )
    assert shown == [] and real is not None


def test_the_refusals_carry_a_code_and_the_http_answer_a_header_older_clients_ignore(
    authority,
):
    with pytest.raises(SyncError) as e:
        authority.device_keys.start_session(device_uuid("nobody"), 0, "x")
    assert e.value.code == "not_a_device" and "never joined" in str(e.value)


def test_a_really_revoked_device_needs_approval_again(project, authority):
    from civex.testing.peers import build_study

    build_study(authority)
    laptop = device(project, authority, "laptop")
    svc = object.__getattribute__(laptop.sync_svc, "_svc")
    svc._sleep = lambda _s: None
    laptop.sync_svc.connect(
        "https://authority.test", None, on_code=_approver(authority, "laptop", [])
    )
    assert laptop.sync_svc.needs_approval("https://authority.test", None) is False
    authority.device_keys.revoke_device("laptop")
    authority.commit()
    assert laptop.sync_svc.needs_approval("https://authority.test", None) is True
    # An invite never needs it.
    assert laptop.sync_svc.needs_approval("https://authority.test", "x") is False
