from __future__ import annotations

from typing import Annotated, Generator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from civexhub.db.models import Repository, User
from civexhub.db.session import get_session
from civexhub.services.repo_service import RepoService
from civexhub.services.token_service import TokenService
from civexhub.services.user_service import UserService


def _get_hub_session() -> Generator[Session, None, None]:
    from civexhub.server.app import get_hub_engine
    session = get_session(get_hub_engine())
    try:
        yield session
    finally:
        session.close()


HubSession = Annotated[Session, Depends(_get_hub_session)]


def get_token_service(session: HubSession) -> TokenService:
    return TokenService(session)


def get_user_service(session: HubSession) -> UserService:
    return UserService(session)


def get_repo_service(session: HubSession) -> RepoService:
    from civexhub.server.app import get_hub_engine, get_object_store
    from civexhub.config import load_config
    return RepoService(
        session=session,
        hub_engine=get_hub_engine(),
        object_store=get_object_store(),
        database_url=load_config().database_url,
    )


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(_get_hub_session),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    raw = authorization.removeprefix("Bearer ").strip()
    token_svc = TokenService(session)
    user = token_svc.validate_token(raw)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    session.commit()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_user_optional(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(_get_hub_session),
) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    raw = authorization.removeprefix("Bearer ").strip()
    token_svc = TokenService(session)
    user = token_svc.validate_token(raw)
    if user:
        session.commit()
    return user


OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
