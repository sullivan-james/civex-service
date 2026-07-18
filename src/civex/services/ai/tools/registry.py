"""Tool registration + dispatch, mirroring plugins/registry.py's pattern.

AI tools are all built-in (no user-authored _civex/tools/*.py discovery need
identified in the epic plan), so unlike plugins/registry.py this only walks
one internal package -- no discover_user_plugins()-style filesystem loading.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

from civex.services.ai.tools.base import AiTool, AiToolContext

TOOL_REGISTRY: dict[str, type[AiTool]] = {}


def register_tool(tool_cls: type[AiTool]) -> None:
    if not getattr(tool_cls, "name", None):
        raise ValueError(f"AiTool {tool_cls.__name__} must define a name")
    if tool_cls.name in TOOL_REGISTRY:
        return
    TOOL_REGISTRY[tool_cls.name] = tool_cls


def all_tools() -> dict[str, type[AiTool]]:
    return dict(TOOL_REGISTRY)


def dispatch(name: str, tool_input: dict, ctx: AiToolContext) -> str:
    try:
        tool_cls = TOOL_REGISTRY.get(name)
        if tool_cls is None:
            return json.dumps({"error": f"unknown tool: {name}"})
        result = tool_cls().run(tool_input, ctx)
    except Exception as e:
        return json.dumps({"error": str(e)})
    return result if isinstance(result, str) else json.dumps(result)


def _discover(package) -> None:
    """Import every module in `package` and register any AiTool subclasses
    it defines at module level."""
    package_path = Path(package.__file__).parent
    for _, module_name, is_pkg in pkgutil.walk_packages(
        path=[str(package_path)], prefix=f"{package.__name__}."
    ):
        if module_name.endswith(".__init__") or is_pkg:
            continue
        module = importlib.import_module(module_name)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, AiTool)
                and attr is not AiTool
            ):
                register_tool(attr)


# Auto-register built-in tools on import.
from civex.services.ai.tools import builtins as _builtins_pkg  # noqa: E402

_discover(_builtins_pkg)
