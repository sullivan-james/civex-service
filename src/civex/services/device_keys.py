"""Who may follow a self-hosted authority: devices it invited, by their keys.

The admin invites a device by name (`invite`: a code that works once, until it
expires). The device joins with the code and its public key (`join`), and from
then on signs in by signing a request with the private key it never sends
(`start_session`), for a token that lasts `SESSION_SECONDS`. `authenticate`
turns that token back into the device, as the authority's `Authenticator`.

Nothing a device sends after joining can be reused for long: a token expires
within minutes, and the key that makes new ones never leaves the device.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from civex import keys
from civex.domain.exceptions import ValidationError
from civex.domain.sync import (
    CLOCK_SKEW_SECONDS,
    INVITE_HOURS,
    INVITE_PREFIX,
    SESSION_SECONDS,
    Joined,
    Principal,
    SessionGrant,
    SyncDeviceDTO,
    SyncError,
    SyncInviteDTO,
    session_answer,
    session_request,
)
from civex.repositories.protocols import SyncRepository

MAX_INVITE_HOURS = 24 * 30


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _refused(message: str) -> SyncError:
    return SyncError(message, retryable=False, status=401)


class DeviceKeys:
    def __init__(self, repo: SyncRepository) -> None:
        self._repo = repo

    # -- the admin's side --------------------------------------------------

    def invite(self, name: str, hours: int = INVITE_HOURS) -> tuple[SyncInviteDTO, str]:
        """Invite a device. The code is returned once: only its hash is kept."""
        name = name.strip()
        if not name:
            raise ValidationError("A device needs a name")
        if not 1 <= hours <= MAX_INVITE_HOURS:
            raise ValidationError(
                f"An invite lasts from 1 hour to {MAX_INVITE_HOURS // 24} days"
            )
        if self._repo.device_named(name) is not None:
            raise ValidationError(
                f"A device called '{name}' already follows this project"
            )
        if any(i.name == name for i in self._repo.pending_invites()):
            raise ValidationError(f"'{name}' already has an invite waiting")
        self._private_key()  # the authority's key, made before anyone can join
        code = INVITE_PREFIX + secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=hours)
        return self._repo.add_invite(name, _hash(code), expires), code

    def pending_invites(self) -> list[SyncInviteDTO]:
        return self._repo.pending_invites()

    def cancel_invite(self, name: str) -> bool:
        return self._repo.cancel_invite(name)

    def list_devices(self) -> list[SyncDeviceDTO]:
        return self._repo.list_devices()

    def revoke_device(self, name: str) -> bool:
        return self._repo.revoke_device(name)

    def has_key(self) -> bool:
        return self._repo.authority_key() is not None

    def fingerprint(self) -> str:
        """This authority's key as people compare it."""
        return keys.fingerprint(keys.public_of(self._private_key()))

    # -- the device's side -------------------------------------------------

    def join(self, invite: str, device_id: str, public_key: str) -> Joined:
        found = self._repo.invite_by_hash(_hash(invite.strip()))
        now = datetime.now(timezone.utc)
        if (
            found is None
            or found.used_at
            or found.revoked_at
            or datetime.fromisoformat(found.expires_at) <= now
        ):
            raise _refused(
                "That invite can't be used: it was used already, it expired, or "
                "it was cancelled. Ask for a new one."
            )
        try:
            device_id = str(uuid.UUID(device_id))
        except ValueError:
            raise SyncError("The device id is not valid", retryable=False)
        if not keys.is_public_key(public_key):
            raise SyncError("The device's key is not valid", retryable=False)
        named = self._repo.device_named(found.name)
        if named is not None and named.device_id != device_id:
            raise _refused(
                f"A device called '{found.name}' already follows this project"
            )
        # Taken only if nobody took it meanwhile (two joins at once).
        if not self._repo.use_invite(found.id):
            raise _refused("That invite was used already. Ask for a new one.")
        # The same machine joining again (connected afresh) replaces itself.
        again = self._repo.live_device(device_id)
        if again is not None:
            self._repo.revoke_device(again.name)
        self._repo.add_device(found.name, device_id, public_key)
        return Joined(
            project_id=self._repo.meta().project_id,
            authority_key=keys.public_of(self._private_key()),
            device_name=found.name,
        )

    def start_session(self, device_id: str, at: int, signature: str) -> SessionGrant:
        device = self._repo.live_device(device_id)
        if device is None:
            raise _refused(
                "This computer is not a device of that server: it never joined, "
                "or it was revoked. Ask for an invite."
            )
        off = at - int(time.time())
        if abs(off) > CLOCK_SKEW_SECONDS:
            raise _refused(
                f"This computer's clock is {abs(off) // 60} minutes "
                f"{'ahead of' if off > 0 else 'behind'} the server's. Set it right "
                "and try again."
            )
        private = self._private_key()
        request = session_request(keys.public_of(private), device_id, at)
        if not keys.verifies(device.public_key, request, signature):
            raise _refused(
                "The sign-in isn't signed with the key this computer joined with "
                "(or it joined a different server at this address)"
            )
        self._repo.touch_device(device.id)
        expires = int(time.time()) + SESSION_SECONDS
        return SessionGrant(
            token=self._token(device.id, expires, private),
            expires_at=expires,
            signature=keys.sign(private, session_answer(signature)),
        )

    def authenticate(self, token: str) -> Principal:
        row, _, rest = token.partition(".")
        expires = rest.partition(".")[0]
        try:
            device_row, until = uuid.UUID(row), int(expires)
        except ValueError:
            raise _refused("Not a session token: sign in again")
        key = self._repo.authority_key()  # none yet: nobody has signed in
        if key is None or not hmac.compare_digest(
            self._token(device_row, until, key), token
        ):
            raise _refused("Not a session token: sign in again")
        if until <= time.time():
            raise _refused("The session expired: sign in again")
        device = self._repo.get_device(device_row)
        if device is None or device.revoked_at:
            raise _refused("This device was revoked")
        return Principal(device.name, device.id, device.device_id)

    # -- the authority's own key -------------------------------------------

    def _private_key(self) -> str:
        key = self._repo.authority_key()
        if key is None:
            key = keys.new_private_key()
            self._repo.set_authority_key(key)
        return key

    @staticmethod
    def _token(device_row: uuid.UUID, expires: int, private_key: str) -> str:
        """A session token: which device, until when, and a MAC keyed by the
        authority's key, so it needs no table and can't be forged."""
        secret = hashlib.sha256(b"civex-session\n" + private_key.encode()).digest()
        body = f"{device_row}.{expires}"
        mac = hmac.new(secret, body.encode(), hashlib.sha256).digest()
        return f"{body}.{base64.urlsafe_b64encode(mac).decode().rstrip('=')}"
