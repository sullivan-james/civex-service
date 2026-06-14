from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from civexhub.domain.dtos import RepoDTO, TokenDTO, UserDTO


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    created_at: datetime

    @classmethod
    def from_dto(cls, dto: UserDTO) -> "UserResponse":
        return cls(
            id=dto.id,
            username=dto.username,
            email=dto.email,
            display_name=dto.display_name,
            bio=dto.bio,
            avatar_url=dto.avatar_url,
            created_at=dto.created_at,
        )


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class CreateTokenRequest(BaseModel):
    username: str
    password: str
    name: str = "default"


class TokenCreatedResponse(BaseModel):
    id: uuid.UUID
    name: str
    token: str
    created_at: datetime


class TokenResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def from_dto(cls, dto: TokenDTO) -> "TokenResponse":
        return cls(
            id=dto.id,
            name=dto.name,
            created_at=dto.created_at,
            last_used_at=dto.last_used_at,
        )


class CreateRepoRequest(BaseModel):
    name: str
    description: str | None = None
    is_public: bool = False


class RepoResponse(BaseModel):
    id: uuid.UUID
    owner: str
    name: str
    description: str | None
    is_public: bool
    created_at: datetime

    @classmethod
    def from_dto(cls, dto: RepoDTO) -> "RepoResponse":
        return cls(
            id=dto.id,
            owner=dto.owner_username,
            name=dto.name,
            description=dto.description,
            is_public=dto.is_public,
            created_at=dto.created_at,
        )
