from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, HTTPException

from civexhub.db.models import RepoAccess
from civexhub.server.deps import CurrentUser, HubSession, get_repo_service
from civexhub.services.org_service import OrgService

router = APIRouter(prefix="/api/v1", tags=["orgs"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CreateOrgRequest(BaseModel):
    name: str
    display_name: str
    description: str | None = None


class AddMemberRequest(BaseModel):
    username: str
    role: str = "member"


class CreateTeamRequest(BaseModel):
    name: str
    description: str | None = None


class AddTeamMemberRequest(BaseModel):
    username: str


class GrantAccessRequest(BaseModel):
    subject_type: str    # "user" | "team" | "org"
    subject_id: str      # UUID of the subject
    role: str            # "read" | "write" | "admin"


class OrgResponse(BaseModel):
    id: str
    name: str
    display_name: str
    description: str | None

    @classmethod
    def from_orm(cls, org) -> "OrgResponse":
        return cls(id=str(org.id), name=org.name, display_name=org.display_name, description=org.description)


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str | None

    @classmethod
    def from_orm(cls, team) -> "TeamResponse":
        return cls(id=str(team.id), name=team.name, description=team.description)


# ---------------------------------------------------------------------------
# Org endpoints
# ---------------------------------------------------------------------------

@router.post("/orgs", response_model=OrgResponse, status_code=201)
def create_org(body: CreateOrgRequest, current_user: CurrentUser, session: HubSession) -> OrgResponse:
    svc = OrgService(session)
    org = svc.create_org(body.name, body.display_name, body.description, current_user.id)
    session.commit()
    return OrgResponse.from_orm(org)


@router.get("/orgs/{org_name}", response_model=OrgResponse)
def get_org(org_name: str, session: HubSession) -> OrgResponse:
    org = OrgService(session).get_org(org_name)
    return OrgResponse.from_orm(org)


@router.post("/orgs/{org_name}/members", status_code=201)
def add_member(org_name: str, body: AddMemberRequest, current_user: CurrentUser, session: HubSession) -> dict:
    svc = OrgService(session)
    org = svc.get_org(org_name)
    if not svc.is_org_owner(org, current_user.id):
        raise HTTPException(status_code=403, detail="Only org owners can add members")
    svc.add_member(org, body.username, body.role)
    session.commit()
    return {"status": "added"}


@router.delete("/orgs/{org_name}/members/{username}", status_code=204)
def remove_member(org_name: str, username: str, current_user: CurrentUser, session: HubSession) -> None:
    svc = OrgService(session)
    org = svc.get_org(org_name)
    if not svc.is_org_owner(org, current_user.id):
        raise HTTPException(status_code=403, detail="Only org owners can remove members")
    svc.remove_member(org, username)
    session.commit()


# ---------------------------------------------------------------------------
# Team endpoints
# ---------------------------------------------------------------------------

@router.post("/orgs/{org_name}/teams", response_model=TeamResponse, status_code=201)
def create_team(org_name: str, body: CreateTeamRequest, current_user: CurrentUser, session: HubSession) -> TeamResponse:
    svc = OrgService(session)
    org = svc.get_org(org_name)
    if not svc.is_org_owner(org, current_user.id):
        raise HTTPException(status_code=403, detail="Only org owners can create teams")
    team = svc.create_team(org, body.name, body.description)
    session.commit()
    return TeamResponse.from_orm(team)


@router.get("/orgs/{org_name}/teams", response_model=list[TeamResponse])
def list_teams(org_name: str, session: HubSession) -> list[TeamResponse]:
    svc = OrgService(session)
    org = svc.get_org(org_name)
    return [TeamResponse.from_orm(t) for t in svc.list_teams(org)]


@router.post("/orgs/{org_name}/teams/{team_name}/members", status_code=201)
def add_team_member(org_name: str, team_name: str, body: AddTeamMemberRequest, current_user: CurrentUser, session: HubSession) -> dict:
    svc = OrgService(session)
    org = svc.get_org(org_name)
    if not svc.is_org_owner(org, current_user.id):
        raise HTTPException(status_code=403, detail="Only org owners can manage team members")
    team = svc.get_team(org, team_name)
    svc.add_team_member(team, body.username)
    session.commit()
    return {"status": "added"}


@router.delete("/orgs/{org_name}/teams/{team_name}/members/{username}", status_code=204)
def remove_team_member(org_name: str, team_name: str, username: str, current_user: CurrentUser, session: HubSession) -> None:
    svc = OrgService(session)
    org = svc.get_org(org_name)
    if not svc.is_org_owner(org, current_user.id):
        raise HTTPException(status_code=403, detail="Only org owners can manage team members")
    team = svc.get_team(org, team_name)
    svc.remove_team_member(team, username)
    session.commit()


# ---------------------------------------------------------------------------
# Repo access grant/revoke
# ---------------------------------------------------------------------------

@router.post("/repos/{owner}/{name}/access", status_code=201)
def grant_access(
    owner: str, name: str, body: GrantAccessRequest, current_user: CurrentUser, session: HubSession
) -> dict:
    import uuid
    from civexhub.services.access_service import get_effective_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    role = get_effective_role(current_user.id, repo, session)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required to manage repo access")

    try:
        subject_uuid = uuid.UUID(body.subject_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="subject_id must be a valid UUID")

    existing = (
        session.query(RepoAccess)
        .filter_by(repo_id=repo.id, subject_type=body.subject_type, subject_id=subject_uuid)
        .first()
    )
    if existing:
        existing.role = body.role
    else:
        session.add(RepoAccess(
            repo_id=repo.id,
            subject_type=body.subject_type,
            subject_id=subject_uuid,
            role=body.role,
        ))
    session.commit()
    return {"status": "granted"}


@router.delete("/repos/{owner}/{name}/access/{subject_type}/{subject_id}", status_code=204)
def revoke_access(
    owner: str, name: str, subject_type: str, subject_id: str,
    current_user: CurrentUser, session: HubSession,
) -> None:
    import uuid
    from civexhub.services.access_service import get_effective_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    role = get_effective_role(current_user.id, repo, session)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required to manage repo access")

    try:
        subject_uuid = uuid.UUID(subject_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="subject_id must be a valid UUID")

    grant = (
        session.query(RepoAccess)
        .filter_by(repo_id=repo.id, subject_type=subject_type, subject_id=subject_uuid)
        .first()
    )
    if grant:
        session.delete(grant)
        session.commit()
