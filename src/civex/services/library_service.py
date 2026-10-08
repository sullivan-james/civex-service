"""Sharing workflows and plugins through the authority's library.

`domain/library.py` says why this is publish-and-install rather than sync. Two
halves, in one service so both read the same rules:

* **The authority's side** (`accept`, `listing`, `item`, `withdraw`): what the
  peer API calls for a device, and what this computer calls when it is the
  authority (`who=None`). It never runs what it holds: a workflow is parsed as
  YAML (aliases refused, so a small file can't expand into a huge one), a
  plugin as Python, and neither is written where civex would load it.
* **Any computer's side** (`browse`, `show`, `publish`, `plan_install`,
  `install`, `unpublish`): the same calls whether the library is this
  project's own (serving) or the authority's (following one), so the authority
  installs from its library exactly as a device does.

Installing is the one moment code from elsewhere becomes something this
computer runs (discovering a plugin runs it), so `plan_install` says first what
would be written, which of it is code, who published it and what starts the
workflow by itself, and `install` refuses anything the plan blocks.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from typing import Protocol

import yaml

from civex.config import Config
from civex.domain.exceptions import NotAllowedError, NotFoundError, ValidationError
from civex.domain.library import (
    ALL,
    DIFFERENT,
    MAX_BUNDLE,
    MAX_ITEMS,
    OFF,
    PLUGIN,
    SAME,
    WORKFLOW,
    InstallPlan,
    InstallStep,
    LibraryItemDTO,
    content_problem,
    here_status,
    is_builtin,
    name_problem,
    provides_problem,
    sha256_of,
)
from civex.domain.sync import Principal, SyncError, SyncTransport
from civex.repositories.protocols import LibraryRepository, SyncRepository
from civex.services.plugin_service import PluginService
from civex.services.workflow_service import WorkflowService
from civex.workflows.definition import WorkflowDef


class _Library(Protocol):
    """Where this project's library is: its own, or its authority's."""

    def listing(self) -> list[LibraryItemDTO]: ...
    def item(self, kind: str, name: str) -> LibraryItemDTO: ...
    def publish(self, items: list[LibraryItemDTO]) -> list[LibraryItemDTO]: ...
    def withdraw(self, kind: str, name: str, force: bool) -> None: ...


def parse_workflow(name: str, content: str) -> WorkflowDef:
    """A shared workflow's text as a definition, without loading anything it
    names. YAML aliases are refused: a few lines of them can expand into
    gigabytes, and a workflow has no use for them."""
    try:
        for event in yaml.parse(content):
            if isinstance(event, yaml.AliasEvent):
                raise ValidationError(
                    f"{name}.yaml uses YAML aliases (*name): a shared workflow can't"
                )
        return WorkflowDef.model_validate(yaml.safe_load(content))
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError(f"{name}.yaml is not a workflow: {e}")


def _triggers(wf: WorkflowDef) -> list[str]:
    out = []
    for event in ("record_created", "record_updated"):
        trigger = getattr(wf.triggers, event, None) if wf.triggers else None
        if trigger is None:
            continue
        text = f"{event} on {trigger.schema_name}"
        if trigger.fields:
            text += f" ({', '.join(trigger.fields)})"
        out.append(text)
    return out


def _needs(wf: WorkflowDef) -> list[str]:
    return sorted({s.plugin for s in wf.steps if not is_builtin(s.plugin)})


class LibraryService:
    def __init__(
        self,
        repo: LibraryRepository,
        sync_repo: SyncRepository,
        config: Config,
        workflow_svc: WorkflowService,
        plugin_svc: PluginService,
        transport: Callable[[], SyncTransport],
        author: Callable[[], str | None],
    ) -> None:
        self._repo = repo
        self._sync = sync_repo
        self._config = config
        self._workflows = workflow_svc
        self._plugins = plugin_svc
        self._transport = transport
        self._author = author

    # ==================================================================
    # The authority's side
    # ==================================================================

    def listing(self) -> list[LibraryItemDTO]:
        return self._repo.all()

    def item(self, kind: str, name: str) -> LibraryItemDTO:
        found = self._repo.get(kind, name)
        if found is None:
            raise NotFoundError(f"The library has no {kind} called '{name}'")
        return found

    def accept(
        self, who: Principal | None, items: list[LibraryItemDTO]
    ) -> list[LibraryItemDTO]:
        """Take a publish: every item, or none of them. `who` is the device
        that sent it, or None for this computer (the authority's own person,
        who may always publish)."""
        if who is not None:
            self._may_publish(who, items)
        if not items:
            raise ValidationError("Nothing to publish")
        if len(items) > MAX_BUNDLE:
            raise ValidationError(
                f"At most {MAX_BUNDLE} files can be published at once"
            )
        keys = [(i.kind, i.name) for i in items]
        if len(set(keys)) != len(keys):
            raise ValidationError("The same file is in the publish twice")
        read = [self._read(i) for i in items]

        offered = {i.provides: i.name for i in read if i.kind == PLUGIN}
        if len(offered) != sum(1 for i in read if i.kind == PLUGIN):
            raise ValidationError(
                "Two plugins in the publish provide the same plugin id"
            )
        held = {(i.kind, i.name): i for i in self._repo.all()}
        for plugin in (i for i in read if i.kind == PLUGIN):
            assert plugin.provides is not None
            owner = self._repo.provider_of(plugin.provides)
            if owner is not None and owner != plugin.name:
                raise ValidationError(
                    f"The plugin '{owner}' in the library already provides "
                    f"'{plugin.provides}'"
                )
            before = held.get((PLUGIN, plugin.name))
            if before and before.provides and before.provides != plugin.provides:
                users = self._needing(before.provides, exclude={i.name for i in read})
                if users:
                    raise ValidationError(
                        f"'{plugin.name}' used to provide '{before.provides}', which "
                        f"{', '.join(users)} in the library need"
                    )
        for wf in (i for i in read if i.kind == WORKFLOW):
            for plugin_id in wf.needs:
                if (
                    plugin_id not in offered
                    and self._repo.provider_of(plugin_id) is None
                ):
                    raise ValidationError(
                        f"The workflow '{wf.name}' uses the plugin '{plugin_id}', which "
                        "isn't in the library: publish it with the workflow"
                    )
        new = sum(1 for k in keys if k not in held)
        if self._repo.count() + new > MAX_ITEMS:
            raise ValidationError(f"The library is full ({MAX_ITEMS} files)")

        by = who.name if who is not None else self._author()
        stored = []
        # Plugins first, so a workflow is never listed before what it needs.
        for i in sorted(read, key=lambda i: i.kind != PLUGIN):
            i.published_by = by
            stored.append(self._repo.put(i))
        return stored

    def withdraw(
        self, who: Principal | None, kind: str, name: str, force: bool = False
    ) -> None:
        if who is not None and not self._device_may_publish(who):
            raise NotAllowedError(
                "This device may not change the library: the server's admin can "
                "allow it (civex sync device allow-publish)"
            )
        found = self.item(kind, name)
        if kind == PLUGIN and found.provides and not force:
            users = self._needing(found.provides)
            if users:
                raise ValidationError(
                    f"{', '.join(users)} in the library use '{name}': remove them "
                    "first, or remove it anyway"
                )
        self._repo.remove(kind, name)

    def _may_publish(self, who: Principal, items: list[LibraryItemDTO]) -> None:
        mode = self._config.sync.library
        if mode == OFF:
            raise NotAllowedError(
                "This server doesn't take shared workflows or plugins"
            )
        if not self._device_may_publish(who):
            raise NotAllowedError(
                f"The device '{who.name}' may not publish to this server's library: "
                "its admin can allow it (civex sync device allow-publish)"
            )
        if mode != ALL and any(i.kind == PLUGIN for i in items):
            raise NotAllowedError(
                "This server takes shared workflows but not plugins (code): its "
                "admin can allow them (civex sync authority library all)"
            )

    def _device_may_publish(self, who: Principal) -> bool:
        device = self._sync.get_device(who.token_id)
        return bool(device and not device.revoked_at and device.may_publish)

    def _needing(self, plugin_id: str, exclude: Collection[str] = ()) -> list[str]:
        return [
            i.name
            for i in self._repo.all()
            if i.kind == WORKFLOW and plugin_id in i.needs and i.name not in exclude
        ]

    def _read(self, item: LibraryItemDTO) -> LibraryItemDTO:
        """An item as the authority keeps it: checked, its details worked out
        from its text alone (never from what the sender says of it, except the
        plugin id a plugin provides, which only running it would tell)."""
        problem = name_problem(item.kind, item.name)
        content = item.content
        if problem is None and not isinstance(content, str):
            problem = f"{item.filename} came without its text"
        if problem is None:
            assert content is not None
            problem = content_problem(item.kind, item.name, content)
        if problem is None and sha256_of(content or "") != item.sha256:
            problem = f"{item.filename} arrived damaged (its hash doesn't match)"
        if problem is None and item.kind == PLUGIN:
            problem = provides_problem(item.provides)
        if problem:
            raise ValidationError(problem)
        assert content is not None
        out = LibraryItemDTO.of(item.kind, item.name, content, provides=None)
        if item.kind == PLUGIN:
            out.provides = item.provides
        else:
            wf = parse_workflow(item.name, content)
            out.title = wf.name[:200]
            out.description = wf.description
            out.needs = _needs(wf)
            out.triggers = _triggers(wf)
        return out

    # ==================================================================
    # Any computer's side
    # ==================================================================

    def _library(self) -> _Library:
        if self._config.sync.serve:
            return _Own(self)
        if self._config.sync.remote:
            return _Theirs(self._transport())
        raise ValidationError(
            "There is no library to share with: workflows and plugins are shared "
            "through a server. Connect to one, or serve this project."
        )

    def browse(self) -> list[LibraryItemDTO]:
        """Everything in the library, with where each stands here."""
        items = self._library().listing()
        registered = self._registered() if any(i.needs for i in items) else {}
        provided = {i.provides for i in items if i.kind == PLUGIN}
        for i in items:
            i.here = here_status(i.sha256, self._local_text(i.kind, i.name))
            i.missing = [
                p for p in i.needs if p not in registered and p not in provided
            ]
        return items

    def show(self, kind: str, name: str) -> LibraryItemDTO:
        """One item with its text, so a person can read it before installing."""
        found = self._library().item(kind, name)
        found.here = here_status(found.sha256, self._local_text(kind, name))
        return found

    def publish(
        self, kind: str, name: str, with_plugins: bool = True
    ) -> list[LibraryItemDTO]:
        """Publish a workflow or plugin from this computer. A workflow goes with
        the plugins its steps use (not built-ins), unless `with_plugins` is off
        and the library already has them."""
        problem = name_problem(kind, name)
        if problem:
            raise ValidationError(problem)
        if kind == PLUGIN:
            items = [self._local_plugin(name, self._plugin_ids_by_file())]
        else:
            path = self._workflows.find_path(name)
            if path is None:
                raise NotFoundError(f"There is no workflow '{name}' here")
            content = path.read_text(encoding="utf-8")
            wf = self._workflows.validate(name, content)  # it works here first
            items = [LibraryItemDTO.of(WORKFLOW, name, content)]
            needs = _needs(wf)
            if with_plugins and needs:
                by_file = self._plugin_ids_by_file()
                files = {pid: f for f, pid in by_file.items()}
                for plugin_id in needs:
                    file = files.get(plugin_id)
                    if file is None:
                        raise ValidationError(
                            f"The workflow uses the plugin '{plugin_id}', which isn't "
                            "a plugin file here (so it can't be published with it)"
                        )
                    items.append(self._local_plugin(file[:-3], by_file))
        return self._library().publish(items)

    def unpublish(self, kind: str, name: str, force: bool = False) -> None:
        self._library().withdraw(kind, name, force)

    def plan_install(
        self, kind: str, name: str, with_plugins: bool = True, replace: bool = False
    ) -> InstallPlan:
        """What installing would write here, and what stops it."""
        return self._plan(kind, name, with_plugins, replace)[0]

    def install(
        self, kind: str, name: str, with_plugins: bool = True, replace: bool = False
    ) -> InstallPlan:
        """Write a library item (and, for a workflow, the plugins it needs) into
        this project. Plugins go first: a plugin is described as it is saved
        (which runs it), and the workflow is then checked against them."""
        plan, texts = self._plan(kind, name, with_plugins, replace)
        if plan.blocked:
            raise ValidationError(" ".join(plan.blocked))
        for step in plan.steps:
            if step.here == SAME:
                continue
            item, content = step.item, texts[(step.item.kind, step.item.name)]
            if item.kind == PLUGIN:
                self._plugins.save(item.name, content)
                provided = self._plugin_ids_by_file().get(item.filename)
                if provided != item.provides:
                    plan.warnings.append(
                        f"{item.filename} was installed, but it doesn't load here as "
                        f"'{item.provides}'"
                        + (f" (it loads as '{provided}')" if provided else "")
                    )
            else:
                old = self._workflows.find_path(item.name)
                self._workflows.save(item.name, content)
                if old is not None and old.suffix == ".yml":
                    old.unlink()  # replaced by the .yaml just written
        return plan

    def _plan(
        self, kind: str, name: str, with_plugins: bool, replace: bool
    ) -> tuple[InstallPlan, dict[tuple[str, str], str]]:
        problem = name_problem(kind, name)
        if problem:
            raise ValidationError(problem)
        library = self._library()
        wanted = [library.item(kind, name)]
        plan = InstallPlan(steps=[])
        if kind == WORKFLOW and wanted[0].needs:
            registered = self._registered()
            providers = {
                i.provides: i.name
                for i in library.listing()
                if i.kind == PLUGIN and i.provides
            }
            for plugin_id in wanted[0].needs:
                if with_plugins and plugin_id in providers:
                    wanted.insert(0, library.item(PLUGIN, providers[plugin_id]))
                elif plugin_id not in registered:
                    plan.blocked.append(
                        f"It uses the plugin '{plugin_id}', which is neither here nor "
                        "in the library."
                    )
        texts: dict[tuple[str, str], str] = {}
        registered_by_file = (
            self._plugin_ids_by_file() if any(i.kind == PLUGIN for i in wanted) else {}
        )
        for item in wanted:
            content = item.content or ""
            texts[(item.kind, item.name)] = content
            local = self._local_text(item.kind, item.name)
            here = here_status(item.sha256, local)
            plan.steps.append(InstallStep(item, self._target(item), here))
            # Never trust the text further than its name and hash.
            problem = name_problem(item.kind, item.name) or content_problem(
                item.kind, item.name, content
            )
            if problem is None and sha256_of(content) != item.sha256:
                problem = f"{item.filename} arrived damaged (its hash doesn't match)."
            if problem:
                plan.blocked.append(problem)
                continue
            if here == DIFFERENT and not replace:
                plan.blocked.append(
                    f"{item.filename} is here already, with different contents: "
                    "replace it, or keep yours."
                )
            if item.kind == PLUGIN and item.provides:
                other = next(
                    (
                        f
                        for f, pid in registered_by_file.items()
                        if pid == item.provides and f != item.filename
                    ),
                    None,
                )
                if other:
                    plan.blocked.append(
                        f"'{item.provides}' is provided here already, by {other}."
                    )
            if item.kind == WORKFLOW:
                for trigger in item.triggers:
                    plan.warnings.append(f"{item.name} runs by itself: {trigger}.")
        return plan, texts

    # -- this computer's files -----------------------------------------

    def _target(self, item: LibraryItemDTO) -> str:
        folder = "workflows" if item.kind == WORKFLOW else "plugins"
        return f"_civex/{folder}/{item.filename}"

    def _local_text(self, kind: str, name: str) -> str | None:
        if kind == WORKFLOW:
            path = self._workflows.find_path(name)
        else:
            path = self._plugins.directory / f"{name}.py"
        if path is None or not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _local_plugin(self, name: str, by_file: dict[str, str]) -> LibraryItemDTO:
        path: Path = self._plugins.directory / f"{name}.py"
        if not path.is_file():
            raise NotFoundError(f"There is no plugin file '{name}.py' here")
        provides = by_file.get(path.name)
        if provides is None:
            raise ValidationError(
                f"{path.name} doesn't load here, so there's nothing to share: fix it "
                "first (Plugins shows why)"
            )
        return LibraryItemDTO.of(
            PLUGIN, name, path.read_text(encoding="utf-8"), provides=provides
        )

    def _plugin_ids_by_file(self) -> dict[str, str]:
        """{filename: plugin id} for the plugin files here that load."""
        return self._plugins.local_plugins()

    def _registered(self) -> set[str]:
        """Every plugin id a workflow here can use: built-ins and this
        project's own plugins."""
        from civex.plugins.registry import all_plugins

        builtins = {pid for pid in all_plugins() if is_builtin(pid)}
        return builtins | set(self._plugin_ids_by_file().values())


class _Own:
    """This project's own library (it is the authority): this computer
    publishes with no device's limits."""

    def __init__(self, svc: LibraryService) -> None:
        self._svc = svc

    def listing(self) -> list[LibraryItemDTO]:
        return self._svc.listing()

    def item(self, kind: str, name: str) -> LibraryItemDTO:
        return self._svc.item(kind, name)

    def publish(self, items: list[LibraryItemDTO]) -> list[LibraryItemDTO]:
        return self._svc.accept(None, items)

    def withdraw(self, kind: str, name: str, force: bool) -> None:
        self._svc.withdraw(None, kind, name, force)


class _Theirs:
    """The authority's library, over the sync connection. What the authority
    refuses comes back in its words, as the error this computer would raise
    for the same refusal; a server that can't be reached stays a `SyncError`."""

    def __init__(self, transport: SyncTransport) -> None:
        self._t = transport

    def _call(self, call, missing: str | None = None):
        try:
            return call()
        except FileNotFoundError:
            raise NotFoundError(missing or "Not in the library")
        except SyncError as e:
            if e.status == 403:
                raise NotAllowedError(str(e))
            if e.status == 404:
                raise ValidationError(
                    "The server has no library of shared workflows: update civex there"
                )
            if not e.retryable and e.status == 400:
                raise ValidationError(str(e))  # it refused what was sent
            raise

    def listing(self) -> list[LibraryItemDTO]:
        return [LibraryItemDTO.from_dict(d) for d in self._call(self._t.library)]

    def item(self, kind: str, name: str) -> LibraryItemDTO:
        return LibraryItemDTO.from_dict(
            self._call(
                lambda: self._t.library_item(kind, name),
                f"The library has no {kind} called '{name}'",
            )
        )

    def publish(self, items: list[LibraryItemDTO]) -> list[LibraryItemDTO]:
        sent = self._call(lambda: self._t.publish([i.to_dict() for i in items]))
        return [LibraryItemDTO.from_dict(d) for d in sent]

    def withdraw(self, kind: str, name: str, force: bool) -> None:
        self._call(
            lambda: self._t.unpublish(kind, name, force),
            f"The library has no {kind} called '{name}'",
        )


__all__ = ["LibraryService", "parse_workflow"]
