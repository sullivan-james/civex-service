from __future__ import annotations

import hashlib
import os
import uuid

from sqlalchemy.orm import Session

from civexhub.db.models import SSHKey, User
from civexhub.domain.dtos import SSHKeyDTO, UserDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError


def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:{salt}:{key.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, _, salt, key_hex = stored.split(":")
    except ValueError:
        return False
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return key.hex() == key_hex


class UserService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_user(self, username: str, email: str, password: str) -> UserDTO:
        if not username or not email or not password:
            raise ValidationError("username, email, and password are required")
        if self._session.query(User).filter_by(username=username).first():
            raise AlreadyExistsError(f"Username '{username}' is already taken")
        if self._session.query(User).filter_by(email=email).first():
            raise AlreadyExistsError(f"Email '{email}' is already registered")
        user = User(
            id=uuid.uuid4(),
            username=username,
            email=email,
            password_hash=_hash_password(password),
        )
        self._session.add(user)
        self._session.flush()
        return _to_dto(user)

    def get_by_username(self, username: str) -> UserDTO | None:
        user = self._session.query(User).filter_by(username=username).first()
        return _to_dto(user) if user else None

    def get_by_id(self, user_id: uuid.UUID) -> UserDTO | None:
        user = self._session.get(User, user_id)
        return _to_dto(user) if user else None

    def authenticate(self, username: str, password: str) -> UserDTO | None:
        user = self._session.query(User).filter_by(username=username).first()
        if user is None or not _verify_password(password, user.password_hash):
            return None
        return _to_dto(user)

    def update_profile(
        self,
        user_id: uuid.UUID,
        *,
        username: str | None = None,
        display_name: str | None = None,
        bio: str | None = None,
        avatar_url: str | None = None,
    ) -> UserDTO:
        user = self._session.get(User, user_id)
        if user is None:
            raise NotFoundError("User not found")
        if username is not None and username != user.username:
            if self._session.query(User).filter_by(username=username).first():
                raise AlreadyExistsError(f"Username '{username}' is already taken")
            user.username = username
        if display_name is not None:
            user.display_name = display_name
        if bio is not None:
            user.bio = bio
        if avatar_url is not None:
            user.avatar_url = avatar_url
        return _to_dto(user)

    def add_ssh_key(self, user_id: uuid.UUID, title: str, public_key: str) -> SSHKeyDTO:
        if not title or not public_key:
            raise ValidationError("title and public_key are required")
        fingerprint = _ssh_fingerprint(public_key)
        if self._session.query(SSHKey).filter_by(public_key=public_key).first():
            raise AlreadyExistsError("This SSH key is already registered")
        key = SSHKey(user_id=user_id, title=title, public_key=public_key, fingerprint=fingerprint)
        self._session.add(key)
        self._session.flush()
        return _key_to_dto(key)

    def list_ssh_keys(self, user_id: uuid.UUID) -> list[SSHKeyDTO]:
        keys = self._session.query(SSHKey).filter_by(user_id=user_id).all()
        return [_key_to_dto(k) for k in keys]

    def delete_ssh_key(self, user_id: uuid.UUID, key_id: uuid.UUID) -> None:
        key = self._session.get(SSHKey, key_id)
        if key is None or key.user_id != user_id:
            raise NotFoundError("SSH key not found")
        self._session.delete(key)

    def _get_orm(self, username: str) -> User | None:
        return self._session.query(User).filter_by(username=username).first()


def _ssh_fingerprint(public_key: str) -> str:
    import base64
    import hashlib
    try:
        key_data = base64.b64decode(public_key.split()[1])
        digest = hashlib.sha256(key_data).digest()
        return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
    except Exception:
        return "unknown"


def _key_to_dto(key: SSHKey) -> SSHKeyDTO:
    return SSHKeyDTO(
        id=key.id,
        user_id=key.user_id,
        title=key.title,
        public_key=key.public_key,
        fingerprint=key.fingerprint,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
    )


def _to_dto(user: User) -> UserDTO:
    return UserDTO(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
    )
