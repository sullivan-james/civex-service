"""Ed25519 keys, as sync uses them: a device's own, and an authority's.

Keys travel and are stored as base64 of their raw 32 bytes. A key's
fingerprint is the short code people compare (`K7QM-29XD`).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _private(key: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(key))


def new_private_key() -> str:
    return _b64(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
    )


def public_of(private_key: str) -> str:
    return _b64(
        _private(private_key).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    )


def sign(private_key: str, message: bytes) -> str:
    return _b64(_private(private_key).sign(message))


def verifies(public_key: str, message: bytes, signature: str) -> bool:
    """Whether `signature` is `public_key`'s over `message`. Anything that
    isn't a key or a signature simply doesn't verify."""
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
            base64.b64decode(signature), message
        )
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def is_public_key(value: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(value, validate=True))
    except (ValueError, TypeError):
        return False
    return True


def fingerprint(public_key: str) -> str:
    """The short code two people compare to know they mean the same key."""
    digest = hashlib.sha256(base64.b64decode(public_key)).digest()
    code = base64.b32encode(digest).decode("ascii")[:8]
    return f"{code[:4]}-{code[4:]}"
