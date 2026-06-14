from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from civexhub.server.deps import CurrentUser, HubSession, OptionalUser, get_repo_service
from civexhub.server.models import CreateRepoRequest, RepoResponse
from civexhub.services.repo_service import RepoService
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1", tags=["repos"])


@router.get("/repos", response_model=list[RepoResponse])
def list_repos(
    current_user: OptionalUser,
    session: HubSession,
) -> list[RepoResponse]:
    svc = get_repo_service(session)
    repos = svc.list_repos(include_private=False)
    if current_user:
        own = svc.list_repos_for_user(current_user.id)
        seen = {r.id for r in repos}
        repos = repos + [r for r in own if r.id not in seen]
    return [RepoResponse.from_dto(r) for r in repos]


@router.post("/repos", response_model=RepoResponse, status_code=201)
def create_repo(
    body: CreateRepoRequest,
    current_user: CurrentUser,
    session: HubSession,
) -> RepoResponse:
    svc = get_repo_service(session)
    try:
        dto = svc.create_repo(current_user, body.name, body.description, body.is_public)
    except AlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    session.commit()
    return RepoResponse.from_dto(dto)


@router.get("/repos/{owner}/{name}", response_model=RepoResponse)
def get_repo(
    owner: str,
    name: str,
    current_user: OptionalUser,
    session: HubSession,
) -> RepoResponse:
    svc = get_repo_service(session)
    dto = svc.get_repo(owner, name)
    if dto is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not dto.is_public and (current_user is None or current_user.id != dto.owner_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return RepoResponse.from_dto(dto)


@router.delete("/repos/{owner}/{name}", status_code=204)
def delete_repo(
    owner: str,
    name: str,
    current_user: CurrentUser,
    session: HubSession,
) -> None:
    svc = get_repo_service(session)
    dto = svc.get_repo(owner, name)
    if dto is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if current_user.id != dto.owner_id:
        raise HTTPException(status_code=403, detail="Only the owner can delete a repository")
    try:
        svc.delete_repo(owner, name)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    session.commit()
