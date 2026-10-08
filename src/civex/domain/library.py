"""The library: workflows and plugins shared through an authority.

Sync carries a project's data. Workflows and plugins are files a person writes,
and a plugin is code: running it is trusting whoever wrote it. So they are not
synced as they change. A person *publishes* one to the authority's library, and
a person on another computer *installs* it from there; nothing arrives in
`_civex/workflows` or `_civex/plugins` by itself, so nothing anyone sent can run
(or even be described, which runs a plugin) until someone here chose it.

The authority keeps what was published as text in its database, never as a file
it would load, and checks it without running it: names, size, that a workflow
parses and that a plugin parses and defines `Plugin`. Its own computer installs
from the library like any device.

Pure: the rules here are shared by the authority, the device and the CLI/API.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

WORKFLOW = "workflow"
PLUGIN = "plugin"
KINDS = (WORKFLOW, PLUGIN)

# What an authority takes from devices (`[sync] library`).
OFF, WORKFLOWS, ALL = "off", "workflows", "all"

# The names a workflow file and a plugin file may have, as WorkflowService and
# PluginService already require of a file saved here.
_NAMES = {
    WORKFLOW: re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,99}$"),
    PLUGIN: re.compile(r"^[a-z][a-z0-9_]{0,99}$"),
}
_PLUGIN_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,199}$")
BUILTIN_PREFIX = "civex."

MAX_BYTES = 256 * 1024  # one file; a plugin or workflow is far smaller
MAX_BUNDLE = 50  # items in one publish
MAX_ITEMS = 1000  # items a library holds

# Where an item stands on this computer.
ABSENT = "absent"  # not here
SAME = "same"  # here, exactly as published
DIFFERENT = "different"  # here, but not the same text (edited here, or updated there)


def sha256_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def filename(kind: str, name: str) -> str:
    return f"{name}.yaml" if kind == WORKFLOW else f"{name}.py"


def is_builtin(plugin_id: str) -> bool:
    return plugin_id.startswith(BUILTIN_PREFIX)


def name_problem(kind: str, name: str) -> str | None:
    if kind not in KINDS:
        return f"'{kind}' is not something the library holds (workflow or plugin)"
    if not _NAMES[kind].match(name or ""):
        if kind == WORKFLOW:
            return (
                f"'{name}' can't be a workflow's name: letters, digits, '-' and "
                "'_' only"
            )
        return (
            f"'{name}' can't be a plugin's name: lowercase letters, digits and "
            "'_' only, starting with a letter"
        )
    return None


def content_problem(kind: str, name: str, content: str) -> str | None:
    """What is wrong with a file's text as text, before anything reads its
    meaning: its size, and for a plugin that it is Python that defines
    `Plugin`. Parsing is not running: nothing in it is executed."""
    size = len(content.encode("utf-8"))
    if size > MAX_BYTES:
        return f"{filename(kind, name)} is {size // 1024} KB: the most is {MAX_BYTES // 1024} KB"
    if "\x00" in content:
        return f"{filename(kind, name)} is not a text file"
    if kind == PLUGIN:
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return f"{filename(kind, name)} is not valid Python: {e}"
        if not any(
            isinstance(node, ast.ClassDef) and node.name == "Plugin"
            for node in ast.walk(tree)
        ):
            return f"{filename(kind, name)} doesn't define a class named 'Plugin'"
    return None


def provides_problem(plugin_id: str | None) -> str | None:
    if not plugin_id or not _PLUGIN_ID.match(plugin_id):
        return "A shared plugin must say which plugin id it provides"
    if is_builtin(plugin_id):
        return f"'{plugin_id}' is a built-in plugin's id: a shared plugin can't take it"
    return None


def here_status(content_sha: str, local_text: str | None) -> str:
    if local_text is None:
        return ABSENT
    return SAME if sha256_of(local_text) == content_sha else DIFFERENT


@dataclass
class LibraryItemDTO:
    """One shared workflow or plugin. `content` is carried only when asked for
    (a listing leaves it out). `provides` is the plugin id a plugin registers as,
    `needs` the plugin ids a workflow's steps use (built-ins left out), and
    `triggers` what starts a workflow by itself ("record_created on sample"), so
    a person installing it sees that before saying yes."""

    kind: str
    name: str
    sha256: str
    size: int
    version: int = 1
    title: str | None = None
    description: str | None = None
    provides: str | None = None
    needs: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    published_by: str | None = None
    published_at: str | None = None
    content: str | None = None
    # Response-only, worked out on the computer asking: where it stands here
    # (`ABSENT`/`SAME`/`DIFFERENT`), and the plugins a workflow needs that are
    # neither here nor in the library.
    here: str | None = None
    missing: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return filename(self.kind, self.name)

    def to_dict(self, with_content: bool = True) -> dict[str, Any]:
        out = {
            "kind": self.kind,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "provides": self.provides,
            "needs": list(self.needs),
            "triggers": list(self.triggers),
            "published_by": self.published_by,
            "published_at": self.published_at,
        }
        if with_content and self.content is not None:
            out["content"] = self.content
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LibraryItemDTO:
        return cls(
            kind=str(data["kind"]),
            name=str(data["name"]),
            sha256=str(data["sha256"]),
            size=int(data.get("size") or 0),
            version=int(data.get("version") or 1),
            title=data.get("title"),
            description=data.get("description"),
            provides=data.get("provides"),
            needs=[str(n) for n in data.get("needs") or []],
            triggers=[str(t) for t in data.get("triggers") or []],
            published_by=data.get("published_by"),
            published_at=data.get("published_at"),
            content=data.get("content"),
        )

    @classmethod
    def of(
        cls, kind: str, name: str, content: str, provides: str | None = None
    ) -> LibraryItemDTO:
        """A file about to be published (its details are filled in by whoever
        reads it: the authority, from the text alone)."""
        return cls(
            kind=kind,
            name=name,
            sha256=sha256_of(content),
            size=len(content.encode("utf-8")),
            provides=provides,
            content=content,
        )


@dataclass
class InstallStep:
    """One file an install writes: what, where it lands, and how it stands now."""

    item: LibraryItemDTO
    path: str
    here: str  # ABSENT / SAME / DIFFERENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(with_content=False),
            "path": self.path,
            "here": self.here,
        }


@dataclass
class InstallPlan:
    """What installing would do. `blocked` says why it can't (a file here that
    differs, unless replacing; a plugin the workflow needs that is nowhere)."""

    steps: list[InstallStep]
    blocked: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def runs_code(self) -> bool:
        return any(s.item.kind == PLUGIN and s.here != SAME for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "blocked": list(self.blocked),
            "warnings": list(self.warnings),
            "runs_code": self.runs_code,
        }
