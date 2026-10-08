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
from collections.abc import Callable
from pathlib import Path

from civex.domain.exceptions import NotFoundError, ValidationError
from civex.workflows.definition import WorkflowDef

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

# Every parsed workflow currently on disk, as (path, def) pairs -- same shape
# as WorkflowService.list_defs(). Taken as a plain callable rather than a
# WorkflowService instance so PluginService doesn't have to depend on it
# directly; mirrors how WorkflowService itself takes a plugins_provider
# rather than a PluginService.
WorkflowsProvider = Callable[[], list[tuple[Path, WorkflowDef]]]


def _io_dicts(specs: list | None) -> list[dict] | None:
    """None passes through as None rather than flattening to [] -- a plugin
    that declares no inputs/outputs contract is a different thing from one
    that declares it has none, and consumers need to keep telling them
    apart (see civex_plugin_sdk.PluginBase.inputs)."""
    return None if specs is None else [spec.model_dump() for spec in specs]


class PluginService:
    def __init__(
        self,
        civex_dir: Path,
        workflows_provider: WorkflowsProvider | None = None,
    ) -> None:
        self._dir = civex_dir / "plugins"
        self._workflows_provider = workflows_provider or (lambda: [])

    @property
    def directory(self) -> Path:
        """`_civex/plugins/`, where a user plugin file lives."""
        return self._dir

    def list_registered(self) -> list[dict]:
        """[{"id", "name", "description", "builtin", "category",
        "capabilities", "inputs", "outputs", "config_schema"}] for every
        registered plugin (built-ins + user plugins discovered from
        _civex/plugins/) -- one plugin's complete declared contract, in the
        one shape every surface (CLI `plugin info`, `GET /plugins`, the
        frontend plugin panel, the AI's authoring guide) reads (CIVEX-144).

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
                "capabilities": list(registration.capabilities),
                "inputs": _io_dicts(registration.inputs),
                "outputs": _io_dicts(registration.outputs),
                "config_schema": (
                    registration.config_schema
                    if registration.config_schema is not None
                    else registration.config_model.model_json_schema()
                ),
                # module_name is a dotted import path for a built-in and the
                # on-disk file path for a user plugin (see
                # _registration_for_subprocess) -- only the latter has a
                # filename an editor can open and save back.
                "filename": (
                    None
                    if plugin_id.startswith(builtin_prefix)
                    else Path(registration.module_name).name
                ),
            }
            for plugin_id, registration in sorted(all_plugins().items())
        ]

    def local_plugins(self) -> dict[str, str]:
        """{filename: plugin id} for the plugin files in this project's
        _civex/plugins/ that load. Scoped to this project's folder, like
        list_load_errors: the registry is process-wide."""
        registered = self._register()
        here = self._dir.resolve()
        found = {}
        for plugin_id, registration in registered.items():
            if plugin_id.startswith("civex."):
                continue
            path = Path(registration.module_name)
            if path.suffix == ".py" and path.resolve().parent == here:
                found[path.name] = plugin_id
        return found

    def list_load_errors(self) -> list[dict]:
        """[{"filename", "error"}] for every user plugin file that most
        recently failed discovery (bad PEP 723 deps, a describe() that
        raises, a timeout, ...) -- these never make it into list_registered()
        since they have no plugin id, so the frontend plugin panel needs this
        separately to show *why* a file it can see in _civex/plugins/ isn't
        usable by any workflow (CIVEX-112)."""
        from civex.plugins.registry import discover_user_plugins, get_load_failures

        discover_user_plugins(self._dir)
        return get_load_failures(self._dir)

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

    def get_source(self, filename: str) -> str:
        """Read one user plugin file's raw source by filename, e.g. to
        populate the editor. `filename` is untrusted input -- reject
        anything that could escape _civex/plugins/ rather than resolving
        and comparing, so a rejected path never touches the filesystem."""
        if "/" in filename or "\\" in filename or filename.startswith("."):
            raise ValidationError("Invalid filename")
        path = self._dir / filename
        if not path.is_file():
            raise NotFoundError(f"Plugin file '{filename}' not found")
        return path.read_text(encoding="utf-8")

    def used_by(self, plugin_id: str) -> list[str]:
        """Filenames of every workflow with a step invoking `plugin_id`."""
        return [
            path.name
            for path, wf in self._workflows_provider()
            if any(step.plugin == plugin_id for step in wf.steps)
        ]

    def delete(self, filename: str, force: bool = False) -> None:
        """Delete a user plugin file. Refuses to delete a plugin still
        referenced by a workflow step (409) unless `force` is set --
        deleting it out from under a workflow would only turn a load-time
        contract check into a confusing run-time failure (CIVEX-119/120,
        mirrors WorkflowService.delete's force pattern). Built-ins have no
        file here and so always 404, same as get_source()."""
        if "/" in filename or "\\" in filename or filename.startswith("."):
            raise ValidationError("Invalid filename")
        path = self._dir / filename
        if not path.is_file():
            raise NotFoundError(f"Plugin file '{filename}' not found")

        registered = self._register()
        plugin_id = next(
            (
                pid
                for pid, registration in registered.items()
                if Path(registration.module_name).name == filename
            ),
            None,
        )
        if not force and plugin_id is not None:
            used_by = self.used_by(plugin_id)
            if used_by:
                raise ValidationError(
                    f"Plugin '{plugin_id}' is used by workflow(s): "
                    f"{', '.join(used_by)}. Remove those steps first, or use "
                    "force=true to delete anyway (those workflows will fail "
                    "contract validation)."
                )

        path.unlink()
        if plugin_id is not None:
            from civex.plugins.registry import unregister_plugin

            unregister_plugin(plugin_id)

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
