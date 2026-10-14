"""What a server does, said once.

Some of civex assumes a machine: drives and file moves, workflows and plugins
in a `_civex/` folder, a terminal, the database it can move, updating itself.
A service hosting many projects does none of that; the devices syncing with it
still do. A `Project` carries the set of features its host offers; a router
that is wholly one feature is included only when the host has it
(`server.app.api_routers`), a route inside a shared router asks
`deps.requires(feature)`, and the frontend reads `GET /api/features` once and
hides what the server doesn't do. Pure: no imports from the rest of civex.
"""

from __future__ import annotations

VOLUMES = "volumes"
STORE_ADMIN = "store_admin"
LOCAL_WORKFLOWS = "local_workflows"
PLUGIN_EDITOR = "plugin_editor"
TERMINAL = "terminal"
DB_ADMIN = "db_admin"
UPDATES = "updates"
LOGS = "logs"
AI = "ai"
OPEN_FOLDER = "open_folder"
DESKTOP = "desktop"
DIRECT_FILES = "direct_files"
ACCOUNTS = "accounts"
HUB_COMPUTE = "hub_compute"

# Every feature a server may offer, with what it means in plain words (the
# detail of the 501 a route answers when its feature is off).
FEATURES: dict[str, str] = {
    VOLUMES: "storage drives, where files are kept, moving and cleaning them up",
    STORE_ADMIN: "choosing where the project's files are kept: drives or a bucket",
    LOCAL_WORKFLOWS: "workflows and runs on this machine",
    PLUGIN_EDITOR: "editing plugins on this machine",
    TERMINAL: "a terminal on this machine",
    DB_ADMIN: "the project's database: moving it, migrating it, Docker",
    UPDATES: "updating civex on this machine",
    LOGS: "the logs civex keeps on this machine",
    AI: "the AI assistant",
    OPEN_FOLDER: "opening a folder on this machine",
    DESKTOP: "a Desktop shortcut and stopping the server on this machine",
    DIRECT_FILES: "uploading and downloading files straight to and from storage",
    ACCOUNTS: "signing in as a person, members and roles",
    HUB_COMPUTE: "running workflows on the server's own compute",
}

# What `civex serve` and the CLI offer: a project in a folder on this machine.
LOCAL_FEATURES: frozenset[str] = frozenset(
    {
        VOLUMES,
        STORE_ADMIN,
        LOCAL_WORKFLOWS,
        PLUGIN_EDITOR,
        TERMINAL,
        DB_ADMIN,
        UPDATES,
        LOGS,
        AI,
        OPEN_FOLDER,
        DESKTOP,
    }
)


def unavailable_message(feature: str) -> str:
    """Why a route answered 501: this server doesn't do that."""
    what = FEATURES.get(feature, feature.replace("_", " "))
    return f"This server doesn't offer {what}."
