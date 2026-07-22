from __future__ import annotations

import hashlib
import importlib
import json
import os
import pkgutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from civex_plugin_sdk.protocol import DescribeResult
from pydantic import BaseModel, ConfigDict, ValidationError

from civex.plugins.base import PluginTier, StepResult, Tier0Plugin, WorkflowContext


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


def _registration_for_tier0(plugin_cls: type[Tier0Plugin]) -> PluginRegistration:
    def invoke(
        inputs: dict[str, Any], config: Any, ctx: WorkflowContext, timeout: float
    ) -> StepResult:
        outputs = plugin_cls().invoke(inputs, config, ctx) or {}
        return StepResult(outputs=outputs)

    return PluginRegistration(
        id=plugin_cls.id,
        name=plugin_cls.name,
        category=plugin_cls.category,
        tier=PluginTier.BUILTIN,
        capabilities=list(plugin_cls.capabilities),
        description=plugin_cls.description,
        inputs=None if plugin_cls.inputs is None else list(plugin_cls.inputs),
        outputs=None if plugin_cls.outputs is None else list(plugin_cls.outputs),
        config_model=plugin_cls.Config,
        module_name=plugin_cls.__module__,
        invoke=invoke,
    )


class _PassthroughConfig(BaseModel):
    """Placeholder config_model for subprocess/container-tier registrations —
    real validation happens inside the plugin's own subprocess via its
    Config.model_validate() (see civex_plugin_sdk.serve._handle_run); the
    host only needs to pass step.config through untouched."""

    model_config = ConfigDict(extra="allow")


def _registration_for_subprocess(
    plugin_path: Path, describe_result: Any
) -> PluginRegistration:
    """Wraps a Tier 1 (uv-managed subprocess) plugin. `describe_result` is
    the DescribeResult obtained once at discovery time; the capabilities it
    declares are closed over here and used to enforce the RPC allowlist at
    run time — never re-derived from the run's own (separate) subprocess."""
    capabilities = list(describe_result.capabilities)

    def invoke(
        inputs: dict[str, Any], config: Any, ctx: WorkflowContext, timeout: float
    ) -> StepResult:
        from civex.plugins.subprocess_runtime import run_plugin

        config_dict = (
            config.model_dump() if isinstance(config, BaseModel) else dict(config)
        )
        return run_plugin(plugin_path, inputs, config_dict, ctx, capabilities, timeout)

    return PluginRegistration(
        id=describe_result.id,
        name=describe_result.name,
        category=describe_result.category,
        tier=PluginTier.SUBPROCESS,
        capabilities=capabilities,
        description=describe_result.description,
        inputs=(
            None if describe_result.inputs is None else list(describe_result.inputs)
        ),
        outputs=(
            None if describe_result.outputs is None else list(describe_result.outputs)
        ),
        config_model=_PassthroughConfig,
        module_name=str(plugin_path),
        invoke=invoke,
        config_schema=describe_result.config_schema,
    )


def register_plugin(plugin_cls: type[Tier0Plugin]) -> None:
    if not hasattr(plugin_cls, "id") or not plugin_cls.id:
        raise ValueError(f"Plugin {plugin_cls.__name__} must define an id")
    if plugin_cls.id in REGISTRY:
        return
    REGISTRY[plugin_cls.id] = _registration_for_tier0(plugin_cls)


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
    if not plugins_dir.exists():
        return

    for path in sorted(plugins_dir.glob("*.py")):
        resolved = path.resolve()
        try:
            content_hash = _content_hash(resolved)
        except OSError:
            continue  # unreadable or vanished mid-scan; nothing to register
        cached = _SUBPROCESS_DESCRIBED.get(resolved)
        if cached is not None and cached[0] == content_hash and cached[1] in REGISTRY:
            continue
        describe_result = _describe_with_disk_cache(path, content_hash)
        registration = _registration_for_subprocess(path, describe_result)
        REGISTRY[registration.id] = registration
        _SUBPROCESS_DESCRIBED[resolved] = (content_hash, registration.id)


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


def get_plugin(plugin_id: str) -> PluginRegistration | None:
    return REGISTRY.get(plugin_id)


def all_plugins() -> dict[str, PluginRegistration]:
    return dict(REGISTRY)


# Auto-register built-ins on import.
from civex.plugins import builtins as _builtins_pkg  # noqa: E402

discover_plugins(_builtins_pkg)
