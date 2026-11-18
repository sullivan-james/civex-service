from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import pkgutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civex_plugin_sdk.plugin import Plugin
from civex_plugin_sdk.plugin_base import IOSpec
from civex_plugin_sdk.serve import describe_result
from civex_plugin_sdk.protocol import DescribeResult
from pydantic import BaseModel, ConfigDict, ValidationError

from civex.plugins import runtime
from civex.plugins.base import PluginTier, StepResult, WorkflowContext
from civex.plugins.launchers import InProcessLauncher, Launcher, UvLauncher

log = logging.getLogger(__name__)


@dataclass
class PluginRegistration:
    """Tier-aware registration wrapping any plugin (built-in or user/custom)
    behind one uniform invoke() -> StepResult, regardless of which tier it
    actually resolves to."""

    id: str
    name: str
    category: str
    tier: PluginTier
    capabilities: list[str]
    description: str
    # Declared step-wiring contract (CIVEX-141): which `inputs:` keys a step
    # may supply and which output names downstream steps may reference. Comes
    # from class attributes for tier BUILTIN and from the `describe` response
    # for the out-of-process tiers -- both ultimately the same IOSpec
    # declarations on civex_plugin_sdk.PluginBase, so no consumer needs a
    # per-tier branch to read a plugin's contract. None means the plugin
    # declares no contract in that direction (see PluginBase.inputs); [] means
    # it declares it has none.
    inputs: list[IOSpec] | None
    outputs: list[IOSpec] | None
    config_model: type[BaseModel]
    module_name: str
    # invoke(inputs, config, ctx, timeout) -> StepResult. `timeout` is always
    # supplied by executor.run() (resolved from StepDef.timeout or
    # [plugins].default_timeout_seconds); tier BUILTIN closures accept and
    # ignore it since in-process execution has no subprocess to bound.
    invoke: Callable[[dict[str, Any], Any, WorkflowContext, float], StepResult]
    # Real JSON schema for a subprocess/container-tier plugin's own Config,
    # captured from its `describe` response -- config_model for those tiers
    # is a permissive passthrough (real validation happens in the
    # subprocess), so callers that want the *actual* schema (PluginService.
    # list_registered) must prefer this over config_model.model_json_schema()
    # when it's set. None for tier BUILTIN, where config_model already *is*
    # the real schema.
    config_schema: dict[str, Any] | None = None


REGISTRY: dict[str, PluginRegistration] = {}

# Resolved path -> (content hash, plugin id) for every subprocess-tier file
# this process has described, so discover_user_plugins doesn't re-spawn a
# `uv run` describe call for a file it already knows -- while still noticing
# when that file's *contents* changed.
#
# Keying on content rather than path is what makes CIVEX-142's revalidation
# affordable: a workflow is revalidated against its plugins' contracts on
# every save and every run, which would otherwise mean a subprocess spawn per
# plugin per validation. An unchanged plugin is a dict lookup; a changed one
# is described again, and the workflows using it fail their next validation
# if its contract no longer fits. That's the lazy trigger -- no reverse index
# of "which workflows use plugin X" is needed.
_SUBPROCESS_DESCRIBED: dict[Path, tuple[str, str]] = {}

# Resolved path -> human-readable error, for every user plugin file that most
# recently failed discovery (bad PEP 723 deps, a describe() that raises, a
# timeout, ...). Populated/cleared by discover_user_plugins() each scan, so it
# always reflects the current contents of _civex/plugins/ rather than history
# -- see get_load_failures(), read by PluginService.list_load_errors() to
# surface these in the plugin list UI (and by run_job()/run_pending_jobs(),
# where the log.warning() below lands in the job log because discovery now
# runs inside their log-capture block) (CIVEX-112).
_LOAD_FAILURES: dict[Path, str] = {}


class _PassthroughConfig(BaseModel):
    """config_model for every registration: real validation happens where the
    plugin runs (its own `Config.model_validate`, in `serve_loop`), so the
    host only passes `step.config` through. `config_schema` (from
    `describe`) is the real schema, for whoever shows or checks it."""

    model_config = ConfigDict(extra="allow")


def _registration(launcher: Launcher, describe_result: Any) -> PluginRegistration:
    """One plugin of any tier, behind one `invoke()`: `runtime.run` with its
    launcher. `describe_result` was obtained once (at discovery, or read off
    a built-in's class); the capabilities it declares are closed over here
    and are what the host functions it calls are checked against, never
    re-derived from the running plugin."""
    capabilities = list(describe_result.capabilities)
    from civex.plugins.host_api import unknown_capabilities

    unknown = unknown_capabilities(capabilities)
    if unknown:
        # Not refused: it may name a function a newer civex has. A call it
        # makes is checked against what it was granted anyway.
        log.warning(
            "Plugin %s lists capabilities this civex doesn't know: %s",
            describe_result.id,
            ", ".join(unknown),
        )
    input_specs = (
        None if describe_result.inputs is None else list(describe_result.inputs)
    )

    def invoke(
        inputs: dict[str, Any], config: Any, ctx: WorkflowContext, timeout: float
    ) -> StepResult:
        config_dict = (
            config.model_dump() if isinstance(config, BaseModel) else dict(config)
        )
        return runtime.run(
            launcher,
            inputs,
            config_dict,
            ctx,
            capabilities,
            timeout,
            input_specs=input_specs,
        )

    return PluginRegistration(
        id=describe_result.id,
        name=describe_result.name,
        category=describe_result.category,
        tier=launcher.tier,
        capabilities=capabilities,
        description=describe_result.description,
        inputs=input_specs,
        outputs=(
            None if describe_result.outputs is None else list(describe_result.outputs)
        ),
        config_model=_PassthroughConfig,
        module_name=launcher.label,
        invoke=invoke,
        config_schema=describe_result.config_schema,
    )


def _registration_for_subprocess(
    plugin_path: Path, describe_result: Any
) -> PluginRegistration:
    return _registration(UvLauncher(plugin_path), describe_result)


def register_plugin(plugin_cls: type[Plugin]) -> None:
    """Register a built-in: run in this process through the protocol like
    any plugin (`InProcessLauncher`), described from its own declarations
    without starting it."""
    if not hasattr(plugin_cls, "id") or not plugin_cls.id:
        raise ValueError(f"Plugin {plugin_cls.__name__} must define an id")
    if plugin_cls.id in REGISTRY:
        return
    REGISTRY[plugin_cls.id] = _registration(
        InProcessLauncher(plugin_cls), describe_result(plugin_cls)
    )


def discover_plugins(package) -> None:
    """Scan a package recursively and register any module that defines a Plugin class."""
    package_path = Path(package.__file__).parent
    for _, module_name, is_pkg in pkgutil.walk_packages(
        path=[str(package_path)],
        prefix=f"{package.__name__}.",
    ):
        if module_name.endswith(".__init__"):
            continue
        module = importlib.import_module(module_name)
        if hasattr(module, "Plugin"):
            register_plugin(module.Plugin)


def discover_user_plugins(plugins_dir: Path) -> None:
    """Register every .py file in a user's _civex/plugins/ directory as a
    Tier 1 (subprocess) plugin: spawn it and ask it to describe itself,
    rather than exec_module-ing it in-process — a plugin file may declare
    arbitrary PEP 723 dependencies that must never be imported into
    civex-service's own process (CIVEX-127).

    A file whose contents are unchanged since this process last described it
    is skipped; an edited one is described again so its new contract takes
    effect immediately (CIVEX-142). Describe results are also cached on disk
    by content hash, so a restart doesn't re-spawn every plugin."""
    resolved_dir = plugins_dir.resolve()
    if not plugins_dir.exists():
        for stale in [p for p in _LOAD_FAILURES if p.parent == resolved_dir]:
            _LOAD_FAILURES.pop(stale, None)
        return

    seen: set[Path] = set()
    for path in sorted(plugins_dir.glob("*.py")):
        resolved = path.resolve()
        seen.add(resolved)
        try:
            content_hash = _content_hash(resolved)
        except OSError:
            continue  # unreadable or vanished mid-scan; nothing to register
        cached = _SUBPROCESS_DESCRIBED.get(resolved)
        if cached is not None and cached[0] == content_hash and cached[1] in REGISTRY:
            _LOAD_FAILURES.pop(resolved, None)
            continue
        try:
            declared = _declared(path)
            if declared is not None:
                # Its header says what it is: nothing is run to find out. Its
                # code is checked against the header when its process starts.
                registration = _registration(
                    UvLauncher(path, declared=declared), declared
                )
            else:
                describe_result = _describe_with_disk_cache(path, content_hash)
                registration = _registration_for_subprocess(path, describe_result)
        except Exception as exc:
            # A single broken plugin file (bad PEP 723 deps, a describe()
            # that raises, a timeout, ...) must not stop discovery of every
            # other file -- only workflows referencing this one are affected.
            log.warning("Failed to load plugin %s: %s", path, exc)
            _LOAD_FAILURES[resolved] = str(exc)
            continue
        REGISTRY[registration.id] = registration
        _SUBPROCESS_DESCRIBED[resolved] = (content_hash, registration.id)
        _LOAD_FAILURES.pop(resolved, None)

    for stale in [
        p for p in _LOAD_FAILURES if p.parent == resolved_dir and p not in seen
    ]:
        _LOAD_FAILURES.pop(stale, None)


def _declared(path: Path) -> DescribeResult | None:
    """The contract `path`'s header declares (`manifest`), checked against
    the protocol versions this civex speaks; None if it declares none."""
    from civex.plugins.manifest import read
    from civex.plugins.runtime import check_protocol_version

    declared = read(path.read_text(encoding="utf-8"))
    return None if declared is None else check_protocol_version(declared)


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _describe_cache_path(plugin_path: Path) -> Path:
    """`_civex/.cache/plugin-describe.json`, alongside the plugins dir the
    file was found in."""
    return plugin_path.resolve().parent.parent / ".cache" / "plugin-describe.json"


def _describe_with_disk_cache(plugin_path: Path, content_hash: str) -> DescribeResult:
    """Describe `plugin_path`, reusing a previous result for identical file
    contents. Any problem reading or writing the cache falls back to (or
    proceeds after) a real describe — a corrupt cache must never be able to
    stop a plugin from loading."""
    cache_path = _describe_cache_path(plugin_path)
    cache = _read_describe_cache(cache_path)
    cached = cache.get(content_hash)
    if cached is not None:
        try:
            return DescribeResult.model_validate(cached)
        except ValidationError:
            pass  # written by a different protocol version; re-describe below

    from civex.plugins.subprocess_runtime import describe_plugin

    describe_result = describe_plugin(plugin_path)
    cache[content_hash] = describe_result.model_dump()
    _write_describe_cache(cache_path, cache)
    return describe_result


def _read_describe_cache(cache_path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_describe_cache(cache_path: Path, cache: dict[str, Any]) -> None:
    """Write via a temp file in the same directory + os.replace, so a
    concurrent reader (the server and a CLI command can both be describing
    plugins in the same project) never sees a half-written file."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=cache_path.name,
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(cache, handle)
            temp_path = Path(handle.name)
        os.replace(temp_path, cache_path)
    except OSError:
        return  # a read-only or full project dir just means no caching


def describe_file(plugin_path: Path) -> DescribeResult:
    """What one plugin file is: the contract its header declares, read
    without running it; else its `describe` answer (which runs it), reusing
    the on-disk cache when its contents were described before. Registers
    nothing: the library uses it to check a version before installing it."""
    declared = _declared(plugin_path)
    if declared is not None:
        return declared
    return _describe_with_disk_cache(plugin_path, _content_hash(plugin_path))


def describe_code(plugin_path: Path) -> DescribeResult:
    """What one plugin file's *code* says it is (its `describe` answer,
    which runs it; cached by contents), for whoever must not take its header
    on trust (the library installing someone else's plugin). When the
    header declares a contract too, the two must agree."""
    from civex.plugins.manifest import differences

    described = _describe_with_disk_cache(plugin_path, _content_hash(plugin_path))
    declared = _declared(plugin_path)
    if declared is not None:
        problems = differences(declared, described)
        if problems:
            raise ValueError(
                "its code doesn't do what its header says: " + "; ".join(problems)
            )
    return described


def registration_from_contract(
    plugin_path: Path, contract: dict[str, Any]
) -> PluginRegistration:
    """A registration from a declared contract (a `describe` answer as JSON),
    for checking workflows against it without running the plugin. Raises
    pydantic's ValidationError if it isn't one."""
    return _registration_for_subprocess(
        plugin_path, DescribeResult.model_validate(contract)
    )


def get_plugin(plugin_id: str) -> PluginRegistration | None:
    return REGISTRY.get(plugin_id)


def all_plugins() -> dict[str, PluginRegistration]:
    return dict(REGISTRY)


def get_load_failures(plugins_dir: Path) -> list[dict[str, str]]:
    """[{"filename", "error"}] for every file directly inside `plugins_dir`
    that failed to load as of the last discover_user_plugins() scan, sorted
    by filename. Scoped to `plugins_dir` (rather than returning every failure
    this process has ever seen) so one project's broken files don't leak into
    another's -- relevant here mainly because REGISTRY/_LOAD_FAILURES are
    process-wide globals and a single process may build_local_context() for
    more than one project directory over its lifetime."""
    resolved_dir = plugins_dir.resolve()
    return [
        {"filename": path.name, "error": error}
        for path, error in sorted(_LOAD_FAILURES.items(), key=lambda item: item[0].name)
        if path.parent == resolved_dir
    ]


def unregister_plugin(plugin_id: str) -> None:
    """Drop a plugin's registration, e.g. after its source file is deleted.
    Also clears its describe-cache entry so a future file of the same name
    is described fresh rather than matched against the deleted file's hash."""
    REGISTRY.pop(plugin_id, None)
    stale_paths = [
        path for path, (_, pid) in _SUBPROCESS_DESCRIBED.items() if pid == plugin_id
    ]
    for path in stale_paths:
        _SUBPROCESS_DESCRIBED.pop(path, None)


# Auto-register built-ins on import.
from civex.plugins import builtins as _builtins_pkg  # noqa: E402

discover_plugins(_builtins_pkg)
