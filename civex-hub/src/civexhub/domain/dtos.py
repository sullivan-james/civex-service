from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class UserDTO:
    id: uuid.UUID
    username: str
    email: str
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    created_at: datetime


@dataclass
class SSHKeyDTO:
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    public_key: str
    fingerprint: str
    created_at: datetime
    last_used_at: datetime | None


@dataclass
class TokenDTO:
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


@dataclass
class RepoDTO:
    id: uuid.UUID
    owner_id: uuid.UUID
    owner_username: str
    name: str
    description: str | None
    is_public: bool
    created_at: datetime
