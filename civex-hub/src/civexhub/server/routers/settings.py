"""User settings: profile, SSH keys, API tokens, org memberships."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from civexhub.server.deps import CurrentUser, HubSession
from civexhub.server.models import TokenCreatedResponse, TokenResponse, UserResponse
from civexhub.services.token_service import TokenService
from civexhub.services.user_service import UserService
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class UpdateProfileRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None


@router.get("/profile", response_model=UserResponse)
def get_profile(current_user: CurrentUser, session: HubSession) -> UserResponse:
    svc = UserService(session)
    dto = svc.get_by_id(current_user.id)
    if dto is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.from_dto(dto)


@router.patch("/profile", response_model=UserResponse)
def update_profile(body: UpdateProfileRequest, current_user: CurrentUser, session: HubSession) -> UserResponse:
    svc = UserService(session)
    try:
        dto = svc.update_profile(
            current_user.id,
            username=body.username,
            display_name=body.display_name,
            bio=body.bio,
            avatar_url=body.avatar_url,
        )
    except AlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    session.commit()
    return UserResponse.from_dto(dto)


# ---------------------------------------------------------------------------
# SSH keys
# ---------------------------------------------------------------------------

class SSHKeyResponse(BaseModel):
    id: uuid.UUID
    title: str
    fingerprint: str
    created_at: datetime
    last_used_at: datetime | None


class AddSSHKeyRequest(BaseModel):
    title: str
    public_key: str


@router.get("/ssh-keys", response_model=list[SSHKeyResponse])
def list_ssh_keys(current_user: CurrentUser, session: HubSession) -> list[SSHKeyResponse]:
    svc = UserService(session)
    keys = svc.list_ssh_keys(current_user.id)
    return [
        SSHKeyResponse(
            id=k.id, title=k.title, fingerprint=k.fingerprint,
            created_at=k.created_at, last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.post("/ssh-keys", response_model=SSHKeyResponse, status_code=201)
def add_ssh_key(body: AddSSHKeyRequest, current_user: CurrentUser, session: HubSession) -> SSHKeyResponse:
    svc = UserService(session)
    try:
        key = svc.add_ssh_key(current_user.id, body.title, body.public_key)
    except (AlreadyExistsError, ValidationError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    session.commit()
    return SSHKeyResponse(
        id=key.id, title=key.title, fingerprint=key.fingerprint,
        created_at=key.created_at, last_used_at=key.last_used_at,
    )


@router.delete("/ssh-keys/{key_id}", status_code=204)
def delete_ssh_key(key_id: uuid.UUID, current_user: CurrentUser, session: HubSession) -> None:
    svc = UserService(session)
    try:
        svc.delete_ssh_key(current_user.id, key_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    session.commit()


# ---------------------------------------------------------------------------
# API tokens (mirrors /auth/tokens but under settings prefix)
# ---------------------------------------------------------------------------

class CreateTokenRequest(BaseModel):
    name: str


@router.get("/tokens", response_model=list[TokenResponse])
def list_tokens(current_user: CurrentUser, session: HubSession) -> list[TokenResponse]:
    token_svc = TokenService(session)
    return [TokenResponse.from_dto(t) for t in token_svc.list_tokens(current_user.id)]


@router.post("/tokens", response_model=TokenCreatedResponse, status_code=201)
def create_token(body: CreateTokenRequest, current_user: CurrentUser, session: HubSession) -> TokenCreatedResponse:
    token_svc = TokenService(session)
    dto, raw = token_svc.create_token(current_user.id, body.name)
    session.commit()
    return TokenCreatedResponse(id=dto.id, name=dto.name, token=raw, created_at=dto.created_at)


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, current_user: CurrentUser, session: HubSession) -> None:
    token_svc = TokenService(session)
    try:
        token_svc.revoke_token(token_id, current_user.id)
    except Exception:
        raise HTTPException(status_code=404, detail="Token not found")
    session.commit()


# ---------------------------------------------------------------------------
# Org memberships
# ---------------------------------------------------------------------------

@router.get("/orgs")
def list_my_orgs(current_user: CurrentUser, session: HubSession) -> list[dict]:
    from civexhub.db.models import OrgMember, Organization
    memberships = (
        session.query(OrgMember, Organization)
        .join(Organization, OrgMember.org_id == Organization.id)
        .filter(OrgMember.user_id == current_user.id)
        .all()
    )
    return [
        {
            "org_id": str(m.org_id),
            "org_name": org.name,
            "org_display_name": org.display_name,
            "role": m.role,
            "joined_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m, org in memberships
    ]
