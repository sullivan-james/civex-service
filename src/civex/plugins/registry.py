from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from civex.plugins.base import BasePlugin

if TYPE_CHECKING:
    pass

PLUGINS: dict[str, type[BasePlugin]] = {}


def register_plugin(plugin_cls: type[BasePlugin]) -> None:
    if not hasattr(plugin_cls, "id") or not plugin_cls.id:
        raise ValueError(f"Plugin {plugin_cls.__name__} must define an id")
    if plugin_cls.id in PLUGINS:
        return
    PLUGINS[plugin_cls.id] = plugin_cls


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
        sys.modules[path.stem] = module   # required before exec so @dataclass can resolve __module__
        spec.loader.exec_module(module)
        if hasattr(module, "Plugin"):
            register_plugin(module.Plugin)


def get_plugin(plugin_id: str) -> type[BasePlugin] | None:
    return PLUGINS.get(plugin_id)


def all_plugins() -> dict[str, type[BasePlugin]]:
    return dict(PLUGINS)


# Auto-register built-ins on import.
from civex.plugins import builtins as _builtins_pkg  # noqa: E402
discover_plugins(_builtins_pkg)
