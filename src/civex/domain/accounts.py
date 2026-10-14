"""Who is using a project, as the host knows them.

A project in a folder is used by whoever sits at the machine: `local`, named
by the chosen name or the OS user, and there is nowhere else to manage
anything. A hosted civex knows a signed-in person, and has a place (its own
pages) where members and roles are managed: `manage_url`, a page listing
the person's projects to go back to (`home_url`), and its own name for this
project (`project`, e.g. `acme / survey`), which the app shows beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LOCAL = "local"
USER = "user"


@dataclass(frozen=True)
class Account:
    name: str
    kind: str = LOCAL  # LOCAL | USER
    manage_url: str | None = None  # where members and roles are managed, if anywhere
    home_url: str | None = None  # the host's page of this person's projects
    project: str | None = None  # what the host calls this project

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "manage_url": self.manage_url,
            "home_url": self.home_url,
            "project": self.project,
        }
