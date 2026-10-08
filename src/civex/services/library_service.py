"""Sharing workflows and plugins through the authority's library.

`domain/library.py` says why this is publish-and-install rather than sync. Two
halves, in one service so both read the same rules:

* **The authority's side** (`accept`, `listing`, `item`, `withdraw`): what the
  peer API calls for a device, and what this computer calls when it is the
  authority (`who=None`). It never runs what it holds: a workflow is parsed as
  YAML (aliases refused, so a small file can't expand into a huge one), a
  plugin as Python, its contract as data, and none of it is written where civex
  would load it.
* **Any computer's side** (`browse`, `show`, `publish`, `plan_install`,
  `install`, `unpublish`): the same calls whether the library is this
  project's own (serving) or the authority's (following one), so the authority
  installs from its library exactly as a device does.

**Versions.** Every publish of new text is the next version, and every version
is kept. A workflow version pins the plugin versions it was published with, and
installing it installs those, so publishing a new plugin version changes no one
who doesn't ask for it. Any version can be installed (a rollback is installing
an earlier one).

**Not breaking what is here.** A plugin version carries the contract its
publisher's computer described (inputs, outputs, config schema). Before an
install writes anything, `plan_install` checks every workflow here that uses a
plugin it would change against the new contract, without running the plugin
(`breaks`); `install` then describes the new code itself, from a staging copy,
and checks again. Either finding blocks the install unless the person installs
anyway (`force`). A breaking change is better published as a new plugin (a new
id), which can sit beside the old one.

Installing is the one moment code from elsewhere becomes something this
computer runs (describing a plugin runs it), so `plan_install` says first what
would be written, which of it is code, who published it and what starts the
workflow by itself, and `install` refuses anything the plan blocks.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from civex.config import Config
from civex.domain.exceptions import NotAllowedError, NotFoundError, ValidationError
from civex.domain.library import (
    ALL,
    MAX_BUNDLE,
    MAX_CONTRACT_BYTES,
    MAX_VERSIONS,
    OFF,
    PLUGIN,
    SAME,
    WORKFLOW,
    InstallPlan,
    InstallStep,
    LibraryItemDTO,
    PublishResult,
    content_problem,
    here_status,
    is_builtin,
    local_version,
    name_problem,
    provides_problem,
    sha256_of,
)
from civex.domain.sync import Principal, SyncError, SyncTransport
from civex.repositories.protocols import LibraryRepository, SyncRepository
from civex.services.plugin_service import PluginService
from civex.services.workflow_service import WorkflowService
from civex.workflows.contract_validation import validate_workflow_contracts
from civex.workflows.definition import WorkflowDef, trigger_summaries

if TYPE_CHECKING:
    from civex.plugins.registry import PluginRegistration


class _Library(Protocol):
    """Where this project's library is: its own, or its authority's."""

    def listing(self) -> list[LibraryItemDTO]: ...
    def item(
        self, kind: str, name: str, version: int | None = None
    ) -> LibraryItemDTO: ...
    def publish(self, items: list[LibraryItemDTO]) -> PublishResult: ...
    def withdraw(
        self, kind: str, name: str, version: int | None, force: bool
    ) -> None: ...


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


def _needs(wf: WorkflowDef) -> list[str]:
    return sorted({s.plugin for s in wf.steps if not is_builtin(s.plugin)})


def _from_contract(name: str, contract: dict[str, Any]) -> PluginRegistration:
    from civex.plugins.registry import registration_from_contract

    return registration_from_contract(Path(f"{name}.py"), contract)


def _errors(wf: WorkflowDef, plugins: dict[str, PluginRegistration]) -> list[str]:
    return [
        f"step '{e.step}': {e.message}" if e.step else e.message
        for e in validate_workflow_contracts(wf, plugins)
    ]


def new_breaks(
    wf: WorkflowDef,
    before: dict[str, PluginRegistration],
    after: dict[str, PluginRegistration],
) -> list[str]:
    """What a workflow gets wrong with the plugins `after` that it didn't with
    those `before`: only what the change causes, not what was already wrong."""
    already = set(_errors(wf, before))
    return [e for e in _errors(wf, after) if e not in already]


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
        """The newest version of everything, each with its history."""
        return self._repo.latest()

    def item(self, kind: str, name: str, version: int | None = None) -> LibraryItemDTO:
        found = self._repo.get(kind, name, version)
        if found is None:
            which = f" version {version}" if version is not None else ""
            raise NotFoundError(f"The library has no {kind} called '{name}'{which}")
        return found

    def accept(
        self, who: Principal | None, items: list[LibraryItemDTO]
    ) -> PublishResult:
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
        plugins = [i for i in read if i.kind == PLUGIN]
        workflows = [i for i in read if i.kind == WORKFLOW]

        offered = {i.provides: i.name for i in plugins}
        if len(offered) != len(plugins):
            raise ValidationError(
                "Two plugins in the publish provide the same plugin id"
            )
        for plugin in plugins:
            assert plugin.provides is not None
            owner = self._repo.provider_of(plugin.provides)
            if owner is not None and owner != plugin.name:
                raise ValidationError(
                    f"The plugin '{owner}' in the library already provides "
                    f"'{plugin.provides}'"
                )
            earlier = self._repo.get(PLUGIN, plugin.name)
            if earlier and earlier.provides != plugin.provides:
                raise ValidationError(
                    f"'{plugin.name}' provides '{earlier.provides}' in the library. "
                    "A plugin keeps its id in every version: publish one with a "
                    "new id under a new name"
                )
        for wf in workflows:
            for plugin_id in wf.needs:
                if (
                    plugin_id not in offered
                    and self._repo.provider_of(plugin_id) is None
                ):
                    raise ValidationError(
                        f"The workflow '{wf.name}' uses the plugin '{plugin_id}', which "
                        "isn't in the library: publish it with the workflow"
                    )
        if self._repo.count() + len(read) > MAX_VERSIONS:
            raise ValidationError(f"The library is full ({MAX_VERSIONS} versions)")

        by = who.name if who is not None else self._author()
        stored: list[LibraryItemDTO] = []
        warnings: list[str] = []
        versions: dict[str, int] = {}  # plugin id -> the version this publish is
        # Plugins first: a workflow pins the versions they become.
        for plugin in plugins:
            plugin.published_by = by
            saved, new = self._repo.add(plugin)
            stored.append(saved)
            assert plugin.provides is not None
            versions[plugin.provides] = saved.version
            if new:
                warnings += self._pinned_elsewhere(plugin, saved.version)
        for wf in workflows:
            wf.published_by = by
            wf.pins = {
                plugin_id: versions.get(plugin_id) or self._newest_version(plugin_id)
                for plugin_id in wf.needs
            }
            stored.append(self._repo.add(wf)[0])
        return PublishResult(stored, warnings)

    def withdraw(
        self,
        who: Principal | None,
        kind: str,
        name: str,
        version: int | None = None,
        force: bool = False,
    ) -> None:
        """Take one version, or every version, out of the library. A plugin
        version a shared workflow is pinned to stays unless `force`."""
        if who is not None and not self._device_may_publish(who):
            raise NotAllowedError(
                "This device may not change the library: the server's admin can "
                "allow it (civex sync device allow-publish)"
            )
        found = self.item(kind, name, version)
        if kind == PLUGIN and found.provides and not force:
            users = self._repo.pinned_by(found.provides, version)
            if users:
                raise ValidationError(
                    f"{', '.join(users)} in the library use{'s' if len(users) == 1 else ''} "
                    f"'{name}'{f' v{version}' if version else ''}: remove "
                    f"{'it' if len(users) == 1 else 'them'} first, or remove it anyway"
                )
        self._repo.remove(kind, name, version)

    def _newest_version(self, plugin_id: str) -> int:
        provider = self._repo.provider_of(plugin_id)
        newest = self._repo.get(PLUGIN, provider) if provider else None
        assert newest is not None  # checked above: it is in the library
        return newest.version

    def _pinned_elsewhere(self, plugin: LibraryItemDTO, version: int) -> list[str]:
        """Shared workflows still on an older version of this plugin that the
        new version would break, by the contracts their publishers declared.
        They keep their pins; whoever installs them alongside the new version
        is told again, and the new version would be better as a new plugin."""
        assert plugin.provides is not None and plugin.contract is not None
        from civex.plugins.registry import all_plugins

        builtins = {k: v for k, v in all_plugins().items() if is_builtin(k)}
        new = _from_contract(plugin.name, plugin.contract)
        out = []
        for wf in self._repo.latest():
            pinned = wf.pins.get(plugin.provides)
            if wf.kind != WORKFLOW or pinned is None or pinned == version:
                continue
            old = self._repo.get(PLUGIN, plugin.name, pinned)
            whole = self._repo.get(WORKFLOW, wf.name, wf.version)
            if old is None or old.contract is None or whole is None:
                continue
            breaks = new_breaks(
                parse_workflow(wf.name, whole.content or ""),
                {
                    **builtins,
                    plugin.provides: _from_contract(plugin.name, old.contract),
                },
                {**builtins, plugin.provides: new},
            )
            if breaks:
                out.append(
                    f"{wf.name} v{wf.version} uses {plugin.name} v{pinned}; "
                    f"v{version} would break it ({'; '.join(breaks)}). It stays on "
                    f"v{pinned}. A change like this is better as a new plugin."
                )
        return out

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

    def _read(self, item: LibraryItemDTO) -> LibraryItemDTO:
        """An item as the authority keeps it: checked, its details worked out
        from its text alone. What only running a plugin would tell (the id it
        provides, its contract) is taken as its publisher says, checked for
        shape, and checked again by whoever installs it."""
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
            problem = provides_problem(item.provides) or self._contract_problem(item)
        if problem:
            raise ValidationError(problem)
        assert content is not None
        out = LibraryItemDTO.of(item.kind, item.name, content)
        if item.kind == PLUGIN:
            out.provides = item.provides
            out.contract = item.contract
        else:
            wf = parse_workflow(item.name, content)
            out.title = wf.name[:200]
            out.description = wf.description
            out.needs = _needs(wf)
            out.triggers = trigger_summaries(wf)
        return out

    @staticmethod
    def _contract_problem(item: LibraryItemDTO) -> str | None:
        contract = item.contract
        if not isinstance(contract, dict):
            return (
                f"{item.filename} came without its contract (inputs, outputs, config)"
            )
        if len(json.dumps(contract)) > MAX_CONTRACT_BYTES:
            return f"{item.filename}'s contract is too big"
        try:
            registration = _from_contract(item.name, contract)
        except Exception as e:
            return f"{item.filename}'s contract can't be read: {e}"
        if registration.id != item.provides:
            return (
                f"{item.filename} says it provides '{item.provides}', but its "
                f"contract is for '{registration.id}'"
            )
        return None

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

    def sharing(self) -> bool:
        """Whether this project has a library to share with."""
        return bool(self._config.sync.serve or self._config.sync.remote)

    def browse(self) -> list[LibraryItemDTO]:
        """The newest version of everything in the library, with where each
        stands here (which version this computer has, if any)."""
        items = self._library().listing()
        registered = self._registered() if any(i.needs for i in items) else set()
        provided = {i.provides for i in items if i.kind == PLUGIN}
        for i in items:
            local = self._local_text(i.kind, i.name)
            i.local_version = local_version(i.history, local)
            i.here = here_status(i.version, i.history, local)
            i.missing = [
                p for p in i.needs if p not in registered and p not in provided
            ]
        return items

    def show(self, kind: str, name: str, version: int | None = None) -> LibraryItemDTO:
        """One version with its text, so a person can read it first."""
        found = self._library().item(kind, name, version)
        local = self._local_text(kind, name)
        found.local_version = local_version(found.history, local)
        found.here = here_status(found.version, found.history, local)
        return found

    def publish(self, kind: str, name: str, with_plugins: bool = True) -> PublishResult:
        """Publish a workflow or plugin from this computer. A workflow goes with
        the plugins its steps use (not built-ins), and is pinned to the versions
        they become; with `with_plugins` off it is pinned to the newest ones
        the library has."""
        problem = name_problem(kind, name)
        if problem:
            raise ValidationError(problem)
        by_file = self._plugin_ids_by_file()
        if kind == PLUGIN:
            items = [self._local_plugin(name, by_file)]
        else:
            path = self._workflows.find_path(name)
            if path is None:
                raise NotFoundError(f"There is no workflow '{name}' here")
            content = path.read_text(encoding="utf-8")
            wf = self._workflows.validate(name, content)  # it works here first
            items = [LibraryItemDTO.of(WORKFLOW, name, content)]
            needs = _needs(wf)
            if with_plugins and needs:
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

    def unpublish(
        self, kind: str, name: str, version: int | None = None, force: bool = False
    ) -> None:
        self._library().withdraw(kind, name, version, force)

    def plan_install(
        self,
        kind: str,
        name: str,
        version: int | None = None,
        with_plugins: bool = True,
        replace: bool = False,
        force: bool = False,
    ) -> InstallPlan:
        """What installing (a version of) an item would write here, and what
        stops it. Runs nothing: breakage is judged from declared contracts."""
        return self._plan(kind, name, version, with_plugins, replace, force)[0]

    def install(
        self,
        kind: str,
        name: str,
        version: int | None = None,
        with_plugins: bool = True,
        replace: bool = False,
        force: bool = False,
    ) -> InstallPlan:
        """Write a library item (and, for a workflow, the plugin versions it is
        pinned to) into this project. New plugin code is described from a
        staging copy first, which runs it, and the workflows here are checked
        against what it really declares; only then is anything written."""
        plan, texts = self._plan(kind, name, version, with_plugins, replace, force)
        if plan.blocked:
            raise ValidationError(" ".join(plan.blocked))
        changing = [s for s in plan.steps if s.here != SAME]
        staged = self._stage([s.item for s in changing if s.item.kind == PLUGIN], texts)
        if not force:
            breaks = self._breaks(
                staged, [s.item for s in changing if s.item.kind == WORKFLOW], texts
            )
            if breaks:
                raise ValidationError(
                    "Installing would break workflows here: "
                    + "; ".join(breaks)
                    + ". Install anyway, or keep the version you have."
                )
        for step in changing:
            item, content = step.item, texts[(step.item.kind, step.item.name)]
            if item.kind == PLUGIN:
                self._plugins.save(item.name, content)
            else:
                old = self._workflows.find_path(item.name)
                if force:
                    self._write_workflow(item.name, content)
                else:
                    self._workflows.save(item.name, content)
                if old is not None and old.suffix == ".yml":
                    old.unlink()  # replaced by the .yaml just written
        return plan

    def _write_workflow(self, name: str, content: str) -> None:
        """Installed anyway: written as published, though it doesn't check out
        against the plugins here (the person said so)."""
        folder = self._plugins.directory.parent / "workflows"
        folder.mkdir(exist_ok=True)
        (folder / f"{name}.yaml").write_text(content, encoding="utf-8")

    def _plan(
        self,
        kind: str,
        name: str,
        version: int | None,
        with_plugins: bool,
        replace: bool,
        force: bool,
    ) -> tuple[InstallPlan, dict[tuple[str, str], str]]:
        problem = name_problem(kind, name)
        if problem:
            raise ValidationError(problem)
        library = self._library()
        wanted = [library.item(kind, name, version)]
        plan = InstallPlan(steps=[])
        top = wanted[0]
        if kind == WORKFLOW and top.needs:
            registered = self._registered()
            providers = {
                i.provides: i.name
                for i in library.listing()
                if i.kind == PLUGIN and i.provides
            }
            for plugin_id in top.needs:
                if with_plugins and plugin_id in providers:
                    pinned = top.pins.get(plugin_id)
                    wanted.insert(0, library.item(PLUGIN, providers[plugin_id], pinned))
                elif plugin_id not in registered:
                    plan.blocked.append(
                        f"It uses the plugin '{plugin_id}', which is neither here nor "
                        "in the library."
                    )
        texts: dict[tuple[str, str], str] = {}
        by_file = (
            self._plugin_ids_by_file() if any(i.kind == PLUGIN for i in wanted) else {}
        )
        for item in wanted:
            content = item.content or ""
            texts[(item.kind, item.name)] = content
            local = self._local_text(item.kind, item.name)
            had = local_version(item.history, local)
            here = here_status(item.version, item.history, local)
            plan.steps.append(InstallStep(item, self._target(item), here, had))
            # Never trust the text further than its name and hash.
            problem = name_problem(item.kind, item.name) or content_problem(
                item.kind, item.name, content
            )
            if problem is None and sha256_of(content) != item.sha256:
                problem = f"{item.filename} arrived damaged (its hash doesn't match)."
            if problem:
                plan.blocked.append(problem)
                continue
            if local is not None and had is None and not replace:
                plan.blocked.append(
                    f"{item.filename} has been changed here (it matches no version in "
                    "the library): replace it, or keep yours."
                )
            if had is not None and had > item.version:
                plan.warnings.append(
                    f"{item.filename} goes back from v{had} to v{item.version}."
                )
            if item.kind == PLUGIN and item.provides:
                other = next(
                    (
                        f
                        for f, pid in by_file.items()
                        if pid == item.provides and f != item.filename
                    ),
                    None,
                )
                if other:
                    plan.blocked.append(
                        f"'{item.provides}' is provided here already, by {other}."
                    )
                if here != SAME and item.contract is None:
                    plan.warnings.append(
                        f"{item.filename} v{item.version} declares no contract, so what "
                        "it would break is checked only when it is installed."
                    )
            if item.kind == WORKFLOW:
                for trigger in item.triggers:
                    plan.warnings.append(f"{item.name} runs by itself: {trigger}.")
        if not plan.blocked:
            changing = [s.item for s in plan.steps if s.here != SAME]
            declared = {}
            for i in changing:
                if i.kind != PLUGIN or not i.provides or not i.contract:
                    continue
                try:
                    declared[i.provides] = _from_contract(i.name, i.contract)
                except Exception:
                    plan.warnings.append(
                        f"{i.filename} v{i.version}'s contract can't be read, so what "
                        "it would break is checked only when it is installed."
                    )
            plan.breaks = self._breaks(
                declared, [i for i in changing if i.kind == WORKFLOW], texts
            )
            if plan.breaks and not force:
                plan.blocked.append(
                    "It would break workflows here (see below): install anyway, or "
                    "keep the version you have. A plugin change like this is better "
                    "published as a new plugin."
                )
        return plan, texts

    def _breaks(
        self,
        new: dict[str, PluginRegistration],
        workflows: list[LibraryItemDTO],
        texts: dict[tuple[str, str], str],
    ) -> list[str]:
        """What the plugin registrations `new` (by id) would break here: in
        the workflows here that use them (only what the change causes), and in
        the workflows being installed (anything wrong with them then)."""
        from civex.plugins.registry import all_plugins

        if not new and not workflows:
            return []
        current = all_plugins()
        after = {**current, **new}
        installing = {w.name for w in workflows}
        out = []
        for path, wf in self._workflows.list_defs():
            if path.stem in installing or not any(s.plugin in new for s in wf.steps):
                continue
            out += [f"{path.stem}: {e}" for e in new_breaks(wf, current, after)]
        for item in workflows:
            wf = parse_workflow(item.name, texts[(WORKFLOW, item.name)])
            out += [f"{item.name}: {e}" for e in _errors(wf, after)]
        return out

    def _stage(
        self, plugins: list[LibraryItemDTO], texts: dict[tuple[str, str], str]
    ) -> dict[str, PluginRegistration]:
        """Describe new plugin versions from a staging copy (this runs them:
        the person installing has said they trust them), so the check after
        is against what the code really declares, not what its publisher said.
        The staging folder is outside `_civex/plugins`, so nothing loads it."""
        from civex.plugins.registry import describe_file, registration_from_contract

        out: dict[str, PluginRegistration] = {}
        if not plugins:
            return out
        staging = self._plugins.directory.parent / ".staging"
        staging.mkdir(exist_ok=True)
        try:
            for item in plugins:
                path = staging / item.filename
                path.write_text(texts[(PLUGIN, item.name)], encoding="utf-8")
                try:
                    described = describe_file(path)
                except Exception as e:
                    raise ValidationError(f"{item.filename} doesn't load here: {e}")
                if described.id != item.provides:
                    raise ValidationError(
                        f"{item.filename} says it provides '{item.provides}', but it "
                        f"loads as '{described.id}'. Nothing was installed."
                    )
                out[described.id] = registration_from_contract(
                    self._plugins.directory / item.filename, described.model_dump()
                )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return out

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
        from civex.plugins.registry import describe_file

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
            PLUGIN,
            name,
            path.read_text(encoding="utf-8"),
            provides=provides,
            # Already described when it loaded: this reads the cache.
            contract=describe_file(path).model_dump(),
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

    def item(self, kind: str, name: str, version: int | None = None) -> LibraryItemDTO:
        return self._svc.item(kind, name, version)

    def publish(self, items: list[LibraryItemDTO]) -> PublishResult:
        return self._svc.accept(None, items)

    def withdraw(self, kind: str, name: str, version: int | None, force: bool) -> None:
        self._svc.withdraw(None, kind, name, version, force)


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

    def item(self, kind: str, name: str, version: int | None = None) -> LibraryItemDTO:
        which = f" version {version}" if version is not None else ""
        return LibraryItemDTO.from_dict(
            self._call(
                lambda: self._t.library_item(kind, name, version),
                f"The library has no {kind} called '{name}'{which}",
            )
        )

    def publish(self, items: list[LibraryItemDTO]) -> PublishResult:
        sent = self._call(lambda: self._t.publish([i.to_dict() for i in items]))
        return PublishResult.from_dict(sent)

    def withdraw(self, kind: str, name: str, version: int | None, force: bool) -> None:
        self._call(
            lambda: self._t.unpublish(kind, name, version, force),
            f"The library has no {kind} called '{name}'",
        )


__all__ = ["LibraryService", "new_breaks", "parse_workflow"]
