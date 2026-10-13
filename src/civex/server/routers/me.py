"""Who is using this project, and what they may do."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from civex.domain.accounts import Account
from civex.domain.permissions import ACTIONS
from civex.project import Project
from civex.server.deps import current_project

router = APIRouter(tags=["status"])


class AccountResponse(BaseModel):
    name: str = Field(description="Who this is: the chosen name or OS user here.")
    kind: str = Field(
        description="`local`: whoever sits at this machine; `user`: a signed-in person."
    )
    manage_url: str | None = Field(
        description="Where members and roles are managed, when the host has such a page."
    )
    home_url: str | None = Field(
        default=None,
        description="The host's page of this person's projects, to go back to.",
    )
    project: str | None = Field(
        default=None, description="What the host calls this project."
    )


class PermissionsResponse(BaseModel):
    actions: dict[str, list[str]] = Field(
        description="Each action this person may do, with where: `project` (everywhere) "
        "or `collection:<id>` entries. An action absent may be done nowhere."
    )
    all: dict[str, str] = Field(
        description="Every action, with what it lets a person do."
    )


class MeResponse(BaseModel):
    account: AccountResponse
    permissions: PermissionsResponse


@router.get("/me", response_model=MeResponse)
def me(project: Project = Depends(current_project)) -> MeResponse:
    """Who is using this project and what they may do (`domain/permissions.py`).
    A project in a folder answers the local user and everything; a hosted one
    the signed-in person and their role. The app reads this once and disables
    what may not be done, saying why."""
    account = project.account or Account(name=project.actor or "you")
    return MeResponse(
        account=AccountResponse(**account.to_dict()),
        permissions=PermissionsResponse(
            actions=project.permissions.to_dict()["actions"], all=dict(ACTIONS)
        ),
    )
