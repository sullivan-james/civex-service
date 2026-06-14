from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from civexhub.db.models import OrgMember, RepoAccess, Repository, TeamMember

_ROLE_RANK = {"read": 1, "write": 2, "admin": 3}


def get_effective_role(user_id: uuid.UUID, repo: Repository, session: Session) -> str | None:
    """Return the highest access role the user has on the repo, or None."""
    roles: list[str] = []

    if repo.owner_id == user_id:
        return "admin"

    if repo.org_id:
        membership = (
            session.query(OrgMember)
            .filter_by(org_id=repo.org_id, user_id=user_id)
            .first()
        )
        if membership and membership.role == "owner":
            return "admin"

    direct = (
        session.query(RepoAccess)
        .filter_by(repo_id=repo.id, subject_type="user", subject_id=user_id)
        .first()
    )
    if direct:
        roles.append(direct.role)

    team_ids = [
        tm.team_id
        for tm in session.query(TeamMember).filter_by(user_id=user_id).all()
    ]
    if team_ids:
        team_grants = (
            session.query(RepoAccess)
            .filter(
                RepoAccess.repo_id == repo.id,
                RepoAccess.subject_type == "team",
                RepoAccess.subject_id.in_(team_ids),
            )
            .all()
        )
        roles.extend(g.role for g in team_grants)

    if repo.org_id:
        org_grant = (
            session.query(RepoAccess)
            .filter_by(repo_id=repo.id, subject_type="org", subject_id=repo.org_id)
            .first()
        )
        if org_grant:
            roles.append(org_grant.role)

    if not roles:
        return None
    return max(roles, key=lambda r: _ROLE_RANK.get(r, 0))


def require_role(user_id: uuid.UUID, repo: Repository, session: Session, minimum: str) -> None:
    from fastapi import HTTPException
    role = get_effective_role(user_id, repo, session)
    if role is None or _ROLE_RANK.get(role, 0) < _ROLE_RANK.get(minimum, 0):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
