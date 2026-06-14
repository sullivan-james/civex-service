from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from civexhub.server.deps import CurrentUser, HubSession, get_user_service
from civexhub.server.models import (
    CreateTokenRequest,
    RegisterRequest,
    TokenCreatedResponse,
    TokenResponse,
    UserResponse,
)
from civexhub.services.token_service import TokenService
from civexhub.services.user_service import UserService
from civex.domain.exceptions import AlreadyExistsError, ValidationError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
def register(body: RegisterRequest, session: HubSession) -> UserResponse:
    svc = UserService(session)
    try:
        dto = svc.create_user(body.username, body.email, body.password)
    except AlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    session.commit()
    return UserResponse.from_dto(dto)


@router.post("/tokens", response_model=TokenCreatedResponse, status_code=201)
def create_token(body: CreateTokenRequest, session: HubSession) -> TokenCreatedResponse:
    user_svc = UserService(session)
    user = user_svc.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token_svc = TokenService(session)
    dto, raw = token_svc.create_token(user.id, body.name)
    session.commit()
    return TokenCreatedResponse(id=dto.id, name=dto.name, token=raw, created_at=dto.created_at)


@router.get("/tokens", response_model=list[TokenResponse])
def list_tokens(current_user: CurrentUser, session: HubSession) -> list[TokenResponse]:
    token_svc = TokenService(session)
    return [TokenResponse.from_dto(t) for t in token_svc.list_tokens(current_user.id)]


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, current_user: CurrentUser, session: HubSession) -> None:
    token_svc = TokenService(session)
    try:
        token_svc.revoke_token(token_id, current_user.id)
    except Exception:
        raise HTTPException(status_code=404, detail="Token not found")
    session.commit()
