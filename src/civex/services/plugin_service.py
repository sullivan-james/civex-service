"""Plugin file management: list registered plugins, list/validate/save raw
plugin source, handle uploads.

Single source of truth for plugin file I/O -- previously duplicated
independently in server/routers/plugins.py and the AI list_plugins/
save_plugin tools (CIVEX-54). Two distinct "list" views are kept separate
because they serve different consumers: list_registered() mirrors the
existing UI plugin browser (built-ins + discovered user plugins, via the
plugin registry), while list_raw() returns full source text of user plugin
files for the AI assistant to read.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from civex.domain.exceptions import ValidationError

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _io_dicts(specs: list | None) -> list[dict] | None:
    """None passes through as None rather than flattening to [] -- a plugin
    that declares no inputs/outputs contract is a different thing from one
    that declares it has none, and consumers need to keep telling them
    apart (see civex_plugin_sdk.PluginBase.inputs)."""
    return None if specs is None else [spec.model_dump() for spec in specs]


class PluginService:
    def __init__(self, civex_dir: Path) -> None:
        self._dir = civex_dir / "plugins"

    def list_registered(self) -> list[dict]:
        """[{"id", "name", "description", "builtin", "category", "inputs",
        "outputs", "config_schema"}] for every registered plugin (built-ins +
        user plugins discovered from _civex/plugins/) -- one plugin's complete
        declared contract, in the one shape every surface reads.

        Nothing here is per-tier: a built-in's contract comes off its class
        attributes and an out-of-process plugin's comes from its `describe`
        response, but both are the same IOSpec/JSON-Schema declarations by the
        time they reach a PluginRegistration, so no caller branches on tier.
        config_schema is the plugin's Config rendered as JSON Schema --
        introspected rather than hand-maintained (CIVEX-56), so it can't drift
        the way the old hardcoded plugin-reference table could."""
        from civex.plugins.registry import all_plugins, discover_user_plugins

        discover_user_plugins(self._dir)
        builtin_prefix = "civex."
        return [
            {
                "id": plugin_id,
                "name": registration.name,
                "description": registration.description,
                "builtin": plugin_id.startswith(builtin_prefix),
                "category": registration.category,
                "inputs": _io_dicts(registration.inputs),
                "outputs": _io_dicts(registration.outputs),
                "config_schema": (
                    registration.config_schema
                    if registration.config_schema is not None
                    else registration.config_model.model_json_schema()
                ),
            }
            for plugin_id, registration in sorted(all_plugins().items())
        ]

    def list_raw(self) -> list[dict]:
        """[{"filename", "code"}] for every *.py file in _civex/plugins/, or
        {"filename", "error"} for one that fails to read -- for the AI
        list_plugins tool, which wants full source text."""
        if not self._dir.exists():
            return []
        results = []
        for path in sorted(self._dir.glob("*.py")):
            try:
                results.append(
                    {"filename": path.name, "code": path.read_text(encoding="utf-8")}
                )
            except Exception as e:
                results.append({"filename": path.name, "error": str(e)})
        return results

    def validate(self, name: str, code: str) -> None:
        """Check name format and that code defines a class named 'Plugin',
        without writing anything. Raises ValidationError on failure."""
        if not _SAFE_NAME.match(name):
            raise ValidationError(
                "name must be lowercase letters, digits, and underscores only"
            )
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise ValidationError(f"Syntax error: {e}")
        has_plugin_class = any(
            isinstance(node, ast.ClassDef) and node.name == "Plugin"
            for node in ast.walk(tree)
        )
        if not has_plugin_class:
            raise ValidationError("Code must define a class named 'Plugin'")

    def save(self, name: str, code: str) -> Path:
        self.validate(name, code)
        self._dir.mkdir(exist_ok=True)
        path = self._dir / f"{name}.py"
        path.write_text(code, encoding="utf-8")
        self._register()
        return path

    def save_uploaded(self, filename: str, content: bytes) -> str:
        """Write an uploaded plugin file verbatim and return its registered
        plugin_id. `filename` must already be sanitized by the caller (the
        router's own path-traversal/extension checks on the untrusted
        multipart upload) -- this only handles the write + registration.

        Subprocess-tier registrations set module_name to the plugin's full
        source path (see registry._registration_for_subprocess), not a bare
        stem -- match on that path directly rather than comparing stems."""
        self._dir.mkdir(exist_ok=True)
        dest = self._dir / filename
        dest.write_bytes(content)
        registered = self._register()
        stem = filename[:-3]
        dest_resolved = dest.resolve()
        return next(
            (
                pid
                for pid, registration in registered.items()
                if pid == stem
                or registration.module_name == stem
                or Path(registration.module_name).resolve() == dest_resolved
            ),
            stem,
        )

    def _register(self) -> dict:
        """Re-run plugin discovery so a just-written file is available in the
        running process without a restart. Returns all_plugins()."""
        from civex.plugins.registry import all_plugins, discover_user_plugins

        discover_user_plugins(self._dir)
        return all_plugins()
