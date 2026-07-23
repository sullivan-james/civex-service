"""Auto-build and content-hash-cache container images for Tier 2 (container)
plugins (CIVEX-148).

A Tier 2 plugin lives at `_civex/plugins/<name>/`: a `civex-plugin.toml`
manifest alongside its Dockerfile and source in the same directory -- the
build context is just "this directory" (see plugin-templates/r and
plugin-templates/java). `ensure_image_built()` computes a content hash over
that directory and tags the built image with it, so the tag *is* the cache
key: an unchanged directory resolves to a tag `docker image inspect` already
finds locally, and `docker build` never runs twice for the same contents --
the same caching idea `uv` already applies to venvs, applied to Docker.
Nothing here drives the plugin's own wire protocol (`docker run -i <image>
<mode>`) -- that's a separate concern (CIVEX-147).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from civex.domain.exceptions import ConfigError, ContainerBuildError

_IMAGE_PREFIX = "civex-plugin"

# Resolved plugin dir -> (content hash, image tag) already confirmed built in
# this process, so an unchanged directory skips even the `docker image
# inspect` round-trip on repeated discovery -- mirrors registry.py's
# _SUBPROCESS_DESCRIBED for Tier 1.
_BUILT: dict[Path, tuple[str, str]] = {}


@dataclass
class ContainerPluginManifest:
    id: str
    name: str
    category: str
    capabilities: list[str] = field(default_factory=list)
    description: str = ""


def load_manifest(plugin_dir: Path) -> ContainerPluginManifest:
    manifest_path = plugin_dir / "civex-plugin.toml"
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"{manifest_path} not found") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{manifest_path} is not valid TOML: {e}") from e

    plugin_id = data.get("id")
    if not plugin_id:
        raise ConfigError(f"{manifest_path} is missing required key 'id'")

    return ContainerPluginManifest(
        id=plugin_id,
        name=data.get("name", plugin_id),
        category=data.get("category", ""),
        capabilities=list(data.get("capabilities", [])),
        description=data.get("description", ""),
    )


def content_hash(plugin_dir: Path) -> str:
    """Hash of every file in the plugin's build context (Dockerfile, source,
    manifest), keyed by relative path so it's independent of directory walk
    order -- the same directory contents always produce the same hash."""
    digest = hashlib.sha256()
    for path in sorted(p for p in plugin_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(plugin_dir).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def image_tag(plugin_id: str, digest: str) -> str:
    safe_id = re.sub(r"[^a-z0-9._-]", "-", plugin_id.lower()).strip("-") or "plugin"
    return f"{_IMAGE_PREFIX}-{safe_id}:{digest[:16]}"


def _run_docker(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise ConfigError(
            "No 'docker' binary found on PATH -- required to build "
            "container-tier (Tier 2) plugins. Install Docker: "
            "https://www.docker.com/products/docker-desktop"
        ) from e


def _image_exists(tag: str) -> bool:
    result = _run_docker(["docker", "image", "inspect", tag])
    return result.returncode == 0


def _docker_build(plugin_dir: Path, tag: str) -> None:
    result = _run_docker(["docker", "build", "-t", tag, str(plugin_dir)])
    if result.returncode != 0:
        raise ContainerBuildError(
            f"docker build failed for plugin image '{tag}':\n{result.stderr.strip()}"
        )


def ensure_image_built(plugin_dir: Path) -> str:
    """Return the image tag for `plugin_dir`'s current contents, invoking
    `docker build` only when no image with that tag already exists locally
    -- no manual `docker build` step required. Raises ConfigError if the
    manifest is missing/invalid or Docker itself isn't available,
    ContainerBuildError if the build fails."""
    resolved = plugin_dir.resolve()
    manifest = load_manifest(resolved)
    digest = content_hash(resolved)

    cached = _BUILT.get(resolved)
    if cached is not None and cached[0] == digest:
        return cached[1]

    tag = image_tag(manifest.id, digest)
    if not _image_exists(tag):
        _docker_build(resolved, tag)
    _BUILT[resolved] = (digest, tag)
    return tag
