"""Tier 2 (container) plugin file management: list container plugin
directories, read/write their files, and rebuild the Docker image on save.

A directory under `_civex/plugins/` is a container plugin (as opposed to a
Tier 1 `.py` file) when it holds both a `Dockerfile` and a `civex-plugin.toml`
manifest -- that pairing is the same marker the plugin-templates/starters
READMEs describe as "what tells the registry this is a container plugin".
There is no host-side container-tier registry/executor yet (PluginTier.
CONTAINER is still "structurally reserved for a later story" -- see
plugins/base.py), so this only covers editing the source tree and building
the image; wiring built images into workflow execution is future work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from civex.domain.exceptions import NotFoundError, ValidationError

_MANIFEST_NAME = "civex-plugin.toml"
_DOCKERFILE_NAME = "Dockerfile"
_BUILD_TIMEOUT_SECONDS = 300


class ContainerPluginService:
    def __init__(self, civex_dir: Path) -> None:
        self._dir = civex_dir / "plugins"

    def list_container_plugins(self) -> list[dict]:
        """[{"name", "files"}] for every subdirectory of _civex/plugins/ that
        has both a Dockerfile and a civex-plugin.toml."""
        if not self._dir.exists():
            return []
        return [
            {"name": path.name, "files": self._list_files(path)}
            for path in sorted(self._dir.iterdir())
            if self._is_container_plugin_dir(path)
        ]

    def get_files(self, name: str) -> dict[str, str]:
        """{relative_path: content} for every text file in the plugin's
        directory. Binary files (e.g. compiled artifacts) are skipped."""
        root = self._plugin_dir(name)
        files = {}
        for rel in self._list_files(root):
            try:
                files[rel] = (root / rel).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
        return files

    def save_file(self, name: str, rel_path: str, content: str) -> None:
        """Write `content` to `rel_path` inside the plugin's directory,
        creating parent directories/the file as needed. Does not rebuild --
        callers that want save-triggers-rebuild call `rebuild()` themselves."""
        root = self._plugin_dir(name)
        target = self._resolve_safe(root, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def rebuild(self, name: str) -> dict:
        """Run `docker build` against the plugin's directory. Never raises --
        a missing docker binary, a timeout, or a failed build are all
        reported as {"success": False, "log": ...} so a save can always
        report a build result rather than 500ing."""
        root = self._plugin_dir(name)
        tag = f"civex-plugin/{name}"
        try:
            proc = subprocess.run(
                ["docker", "build", "-t", tag, str(root)],
                capture_output=True,
                text=True,
                timeout=_BUILD_TIMEOUT_SECONDS,
            )
            return {"success": proc.returncode == 0, "log": proc.stdout + proc.stderr}
        except FileNotFoundError:
            return {"success": False, "log": "docker executable not found on PATH"}
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "log": f"docker build timed out after {_BUILD_TIMEOUT_SECONDS}s",
            }

    def _is_container_plugin_dir(self, path: Path) -> bool:
        return (
            path.is_dir()
            and (path / _DOCKERFILE_NAME).is_file()
            and (path / _MANIFEST_NAME).is_file()
        )

    def _list_files(self, root: Path) -> list[str]:
        return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())

    def _plugin_dir(self, name: str) -> Path:
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValidationError("Invalid container plugin name")
        root = self._dir / name
        if not self._is_container_plugin_dir(root):
            raise NotFoundError(f"Container plugin '{name}' not found")
        return root

    def _resolve_safe(self, root: Path, rel_path: str) -> Path:
        """Reject any rel_path that would write outside `root` (absolute
        paths, `..` escapes)."""
        candidate = (root / rel_path).resolve()
        root_resolved = root.resolve()
        if candidate != root_resolved and root_resolved not in candidate.parents:
            raise ValidationError("Invalid file path")
        return candidate
