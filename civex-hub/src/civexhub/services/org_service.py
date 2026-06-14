from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from civexhub.db.models import Organization, OrgMember, Team, TeamMember, User


class OrgService:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create_org(self, name: str, display_name: str, description: str | None, founder_id: uuid.UUID) -> Organization:
        existing = self._s.query(Organization).filter_by(name=name).first()
        if existing:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=f"Organization '{name}' already exists")
        org = Organization(name=name, display_name=display_name, description=description)
        self._s.add(org)
        self._s.flush()
        self._s.add(OrgMember(org_id=org.id, user_id=founder_id, role="owner"))
        self._s.flush()
        return org

    def get_org(self, name: str) -> Organization:
        org = self._s.query(Organization).filter_by(name=name).first()
        if not org:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Organization '{name}' not found")
        return org

    def add_member(self, org: Organization, username: str, role: str = "member") -> OrgMember:
        user = self._s.query(User).filter_by(username=username).first()
        if not user:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        existing = self._s.query(OrgMember).filter_by(org_id=org.id, user_id=user.id).first()
        if existing:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=f"'{username}' is already a member")
        member = OrgMember(org_id=org.id, user_id=user.id, role=role)
        self._s.add(member)
        self._s.flush()
        return member

    def remove_member(self, org: Organization, username: str) -> None:
        user = self._s.query(User).filter_by(username=username).first()
        if not user:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        member = self._s.query(OrgMember).filter_by(org_id=org.id, user_id=user.id).first()
        if not member:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"'{username}' is not a member")
        self._s.delete(member)
        self._s.flush()

    def create_team(self, org: Organization, name: str, description: str | None) -> Team:
        existing = self._s.query(Team).filter_by(org_id=org.id, name=name).first()
        if existing:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=f"Team '{name}' already exists in this org")
        team = Team(org_id=org.id, name=name, description=description)
        self._s.add(team)
        self._s.flush()
        return team

    def list_teams(self, org: Organization) -> list[Team]:
        return self._s.query(Team).filter_by(org_id=org.id).all()

    def get_team(self, org: Organization, name: str) -> Team:
        team = self._s.query(Team).filter_by(org_id=org.id, name=name).first()
        if not team:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Team '{name}' not found")
        return team

    def add_team_member(self, team: Team, username: str) -> TeamMember:
        user = self._s.query(User).filter_by(username=username).first()
        if not user:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        existing = self._s.query(TeamMember).filter_by(team_id=team.id, user_id=user.id).first()
        if existing:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=f"'{username}' is already in this team")
        member = TeamMember(team_id=team.id, user_id=user.id)
        self._s.add(member)
        self._s.flush()
        return member

    def remove_team_member(self, team: Team, username: str) -> None:
        user = self._s.query(User).filter_by(username=username).first()
        if not user:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        member = self._s.query(TeamMember).filter_by(team_id=team.id, user_id=user.id).first()
        if not member:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"'{username}' is not in this team")
        self._s.delete(member)
        self._s.flush()

    def is_org_owner(self, org: Organization, user_id: uuid.UUID) -> bool:
        member = self._s.query(OrgMember).filter_by(org_id=org.id, user_id=user_id, role="owner").first()
        return member is not None
