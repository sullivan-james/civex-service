from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from civex.plugins.base import (
    BasePlugin,
    PluginTier,
    StepResult,
    Tier0Plugin,
    WorkflowContext,
)


@dataclass
class PluginRegistration:
    """Tier-aware registration wrapping any plugin (built-in or user/custom)
    behind one uniform invoke() -> StepResult, regardless of which tier it
    actually resolves to. Only PluginTier.BUILTIN is populated today —
    SUBPROCESS/CONTAINER dispatch lands in CIVEX-127+."""

    id: str
    name: str
    category: str
    tier: PluginTier
    capabilities: list[str]
    description: str
    config_model: type[BaseModel]
    module_name: str
    invoke: Callable[[dict[str, Any], Any, WorkflowContext], StepResult]


REGISTRY: dict[str, PluginRegistration] = {}


def _registration_for_tier0(plugin_cls: type[Tier0Plugin]) -> PluginRegistration:
    def invoke(inputs: dict[str, Any], config: Any, ctx: WorkflowContext) -> StepResult:
        outputs = plugin_cls().invoke(inputs, config, ctx) or {}
        return StepResult(outputs=outputs)

    return PluginRegistration(
        id=plugin_cls.id,
        name=plugin_cls.name,
        category=plugin_cls.category,
        tier=PluginTier.BUILTIN,
        capabilities=list(plugin_cls.capabilities),
        description=getattr(plugin_cls, "description", "") or "",
        config_model=plugin_cls.Config,
        module_name=plugin_cls.__module__,
        invoke=invoke,
    )


def _registration_for_legacy(plugin_cls: type[BasePlugin]) -> PluginRegistration:
    """Wraps today's user _civex/plugins/*.py contract (BasePlugin.run,
    unchanged) so it registers uniformly alongside Tier0Plugin built-ins.
    Still executes in-process today; moves to tier SUBPROCESS in CIVEX-127
    without user plugin files needing to change."""

    def invoke(inputs: dict[str, Any], config: Any, ctx: WorkflowContext) -> StepResult:
        outputs = plugin_cls().run(inputs, config, ctx) or {}
        return StepResult(outputs=outputs)

    return PluginRegistration(
        id=plugin_cls.id,
        name=plugin_cls.name,
        category=plugin_cls.category,
        tier=PluginTier.BUILTIN,
        capabilities=list(getattr(plugin_cls, "capabilities", []) or []),
        description=getattr(plugin_cls, "description", "") or "",
        config_model=plugin_cls.Config,
        module_name=plugin_cls.__module__,
        invoke=invoke,
    )


def register_plugin(plugin_cls: type[Tier0Plugin] | type[BasePlugin]) -> None:
    if not hasattr(plugin_cls, "id") or not plugin_cls.id:
        raise ValueError(f"Plugin {plugin_cls.__name__} must define an id")
    if plugin_cls.id in REGISTRY:
        return
    if issubclass(plugin_cls, Tier0Plugin):
        REGISTRY[plugin_cls.id] = _registration_for_tier0(plugin_cls)
    else:
        REGISTRY[plugin_cls.id] = _registration_for_legacy(plugin_cls)


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
    """Load .py files from a user's _civex/plugins/ directory."""
    if not plugins_dir.exists():
        return
    for path in sorted(plugins_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = (
            module  # required before exec so @dataclass can resolve __module__
        )
        spec.loader.exec_module(module)
        if hasattr(module, "Plugin"):
            register_plugin(module.Plugin)


def get_plugin(plugin_id: str) -> PluginRegistration | None:
    return REGISTRY.get(plugin_id)


def all_plugins() -> dict[str, PluginRegistration]:
    return dict(REGISTRY)


# Auto-register built-ins on import.
from civex.plugins import builtins as _builtins_pkg  # noqa: E402

discover_plugins(_builtins_pkg)
