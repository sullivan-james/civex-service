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
SERVER_PATH_EXPORT = "server_path_export"
PLUGIN_INSTALL = "plugin_install"
REMOTE_DIAL = "remote_dial"
RELEASES = "releases"
SETTINGS = "settings"
SETTINGS_APPEARANCE = "settings_appearance"
SETTINGS_RETENTION = "settings_retention"
SETTINGS_MAP = "settings_map"
SETTINGS_ADVANCED = "settings_advanced"
SETTINGS_DEVICES = "settings_devices"
SETTINGS_MEMBERS = "settings_members"

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
    SERVER_PATH_EXPORT: "writing exports to a folder on the server's machine",
    PLUGIN_INSTALL: "installing plugins and workflows from a bundle onto the server",
    REMOTE_DIAL: "connecting out from the server to another civex",
    RELEASES: "releases: permanent, citable versions of the data, published on a host",
    SETTINGS: "the Settings area",
    SETTINGS_APPEARANCE: "appearance settings",
    SETTINGS_RETENTION: "the retention settings",
    SETTINGS_MAP: "map settings",
    SETTINGS_ADVANCED: "advanced settings",
    SETTINGS_DEVICES: "the Devices section of the settings",
    SETTINGS_MEMBERS: "the members and access page",
}

# The settings surfaces a host that owns all settings turns off. `SETTINGS` is
# the whole area; each of the others is one section of it. A section feature
# hides that section of the app and refuses only the routes that edit its
# stored settings, never the operational routes a host drives itself.
SETTINGS_FEATURES: frozenset[str] = frozenset(
    {
        SETTINGS,
        SETTINGS_APPEARANCE,
        SETTINGS_RETENTION,
        SETTINGS_MAP,
        SETTINGS_ADVANCED,
        SETTINGS_DEVICES,
        SETTINGS_MEMBERS,
    }
)

# What `civex serve` and the CLI offer: a project in a folder on this machine.
# `RELEASES` is not among them, on purpose: a release is published by a host
# (a hub), never made on a personal device, so only a host turns it on.
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
        SERVER_PATH_EXPORT,
        PLUGIN_INSTALL,
        REMOTE_DIAL,
    }
    | SETTINGS_FEATURES
)


def lacks(features: frozenset[str] | set[str], feature: str) -> str | None:
    """The feature to blame when `feature` is not on, or None when it is: a
    settings section is off whenever the `SETTINGS` umbrella is, whatever the
    section's own feature says. The one place that rule is written down (the
    app's `utils/features.ts` mirrors it)."""
    if (
        feature in SETTINGS_FEATURES
        and feature != SETTINGS
        and SETTINGS not in features
    ):
        return SETTINGS
    return None if feature in features else feature


def enabled(features: frozenset[str] | set[str], feature: str) -> bool:
    """Whether a host offering `features` offers `feature` (see `lacks`)."""
    return lacks(features, feature) is None


def unavailable_message(feature: str) -> str:
    """Why a route answered 501: this server doesn't do that."""
    what = FEATURES.get(feature, feature.replace("_", " "))
    return f"This server doesn't offer {what}."
