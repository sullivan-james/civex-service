from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict

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

# Path (resolved) -> plugin id, so discover_user_plugins doesn't re-spawn a
# `uv run` describe call for a file it's already registered within this
# process's lifetime -- mirrors register_plugin's own "register once"
# dedup-by-id behavior for the other tiers.
_SUBPROCESS_DESCRIBED: dict[Path, str] = {}


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
    civex-service's own process (CIVEX-127). Files already registered from
    this exact path are not re-described within this process's lifetime."""
    if not plugins_dir.exists():
        return

    from civex.plugins.subprocess_runtime import describe_plugin

    for path in sorted(plugins_dir.glob("*.py")):
        resolved = path.resolve()
        cached_id = _SUBPROCESS_DESCRIBED.get(resolved)
        if cached_id is not None and cached_id in REGISTRY:
            continue
        describe_result = describe_plugin(path)
        registration = _registration_for_subprocess(path, describe_result)
        REGISTRY[registration.id] = registration
        _SUBPROCESS_DESCRIBED[resolved] = registration.id


def get_plugin(plugin_id: str) -> PluginRegistration | None:
    return REGISTRY.get(plugin_id)


def all_plugins() -> dict[str, PluginRegistration]:
    return dict(REGISTRY)


# Auto-register built-ins on import.
from civex.plugins import builtins as _builtins_pkg  # noqa: E402

discover_plugins(_builtins_pkg)
