"""Auto-build and content-hash-cache of Tier 2 (container) plugin images
(CIVEX-148). `docker` isn't invoked for real here -- `_run_docker` is
monkeypatched so these stay fast/hermetic, the same approach
test_subprocess_runtime.py uses for `uv`-specific bits."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from civex.domain.exceptions import ConfigError, ContainerBuildError
from civex.plugins import container_build as cb


def _write_plugin_dir(
    tmp_path: Path, name: str = "plugin", plugin_id: str = "example.echo"
) -> Path:
    plugin_dir = tmp_path / name
    plugin_dir.mkdir()
    (plugin_dir / "civex-plugin.toml").write_text(
        f'id = "{plugin_id}"\n'
        'name = "Echo"\n'
        'category = "example"\n'
        'capabilities = ["commit"]\n'
    )
    (plugin_dir / "Dockerfile").write_text("FROM scratch\n")
    return plugin_dir


# -- manifest -----------------------------------------------------------


def test_load_manifest_reads_declared_fields(tmp_path: Path) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    manifest = cb.load_manifest(plugin_dir)
    assert manifest.id == "example.echo"
    assert manifest.name == "Echo"
    assert manifest.category == "example"
    assert manifest.capabilities == ["commit"]


def test_load_manifest_defaults_name_to_id(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "civex-plugin.toml").write_text('id = "example.minimal"\n')
    manifest = cb.load_manifest(plugin_dir)
    assert manifest.name == "example.minimal"
    assert manifest.category == ""
    assert manifest.capabilities == []


def test_load_manifest_missing_file_raises(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    with pytest.raises(ConfigError, match="civex-plugin.toml"):
        cb.load_manifest(plugin_dir)


def test_load_manifest_missing_id_raises(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "civex-plugin.toml").write_text('name = "No Id"\n')
    with pytest.raises(ConfigError, match="'id'"):
        cb.load_manifest(plugin_dir)


def test_load_manifest_invalid_toml_raises(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "civex-plugin.toml").write_text("not valid [[[ toml")
    with pytest.raises(ConfigError, match="not valid TOML"):
        cb.load_manifest(plugin_dir)


# -- content hash ---------------------------------------------------------


def test_content_hash_stable_across_calls(tmp_path: Path) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    assert cb.content_hash(plugin_dir) == cb.content_hash(plugin_dir)


def test_content_hash_independent_of_directory_walk_order(tmp_path: Path) -> None:
    a = _write_plugin_dir(tmp_path, name="a")
    (a / "src.py").write_text("print(1)\n")

    b_dir = tmp_path / "b"
    b_dir.mkdir()
    (b_dir / "src.py").write_text("print(1)\n")
    (b_dir / "Dockerfile").write_text("FROM scratch\n")
    (b_dir / "civex-plugin.toml").write_text(
        'id = "example.echo"\nname = "Echo"\ncategory = "example"\n'
        'capabilities = ["commit"]\n'
    )

    assert cb.content_hash(a) == cb.content_hash(b_dir)


def test_content_hash_changes_when_a_file_changes(tmp_path: Path) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    before = cb.content_hash(plugin_dir)
    (plugin_dir / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    after = cb.content_hash(plugin_dir)
    assert before != after


def test_content_hash_changes_when_a_file_is_added(tmp_path: Path) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    before = cb.content_hash(plugin_dir)
    (plugin_dir / "extra.txt").write_text("new file\n")
    after = cb.content_hash(plugin_dir)
    assert before != after


# -- image tag --------------------------------------------------------------


def test_image_tag_sanitizes_plugin_id() -> None:
    tag = cb.image_tag("Example/Project.Echo!", "0123456789abcdef")
    assert tag.startswith("civex-plugin-")
    assert "/" not in tag.split(":")[0].removeprefix("civex-plugin-")
    assert tag.endswith(":0123456789abcdef")


def test_image_tag_falls_back_when_id_sanitizes_to_empty() -> None:
    tag = cb.image_tag("!!!", "0123456789abcdef")
    assert tag == "civex-plugin-plugin:0123456789abcdef"


# -- ensure_image_built: docker interactions mocked --------------------------


def test_ensure_image_built_builds_when_no_cached_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    monkeypatch.setattr(cb, "_BUILT", {})
    monkeypatch.setattr(cb, "_image_exists", lambda tag: False)

    built: list[tuple[Path, str]] = []

    def fake_build(directory: Path, tag: str) -> None:
        built.append((directory, tag))

    monkeypatch.setattr(cb, "_docker_build", fake_build)

    tag = cb.ensure_image_built(plugin_dir)
    assert built == [(plugin_dir.resolve(), tag)]
    assert tag.startswith("civex-plugin-example.echo:")


def test_ensure_image_built_skips_build_when_image_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    monkeypatch.setattr(cb, "_BUILT", {})
    monkeypatch.setattr(cb, "_image_exists", lambda tag: True)

    def _boom(*args, **kwargs):
        raise AssertionError("docker build should not run for an existing tag")

    monkeypatch.setattr(cb, "_docker_build", _boom)

    tag = cb.ensure_image_built(plugin_dir)
    assert tag.startswith("civex-plugin-example.echo:")


def test_ensure_image_built_uses_in_memory_cache_for_unchanged_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    monkeypatch.setattr(cb, "_BUILT", {})
    monkeypatch.setattr(cb, "_docker_build", lambda *a, **k: None)
    monkeypatch.setattr(cb, "_image_exists", lambda tag: False)

    first = cb.ensure_image_built(plugin_dir)

    def _boom(tag):
        raise AssertionError("docker image inspect should not run again")

    monkeypatch.setattr(cb, "_image_exists", _boom)
    second = cb.ensure_image_built(plugin_dir)
    assert first == second


def test_ensure_image_built_rebuilds_after_directory_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = _write_plugin_dir(tmp_path)
    monkeypatch.setattr(cb, "_BUILT", {})
    monkeypatch.setattr(cb, "_docker_build", lambda *a, **k: None)
    monkeypatch.setattr(cb, "_image_exists", lambda tag: False)

    first = cb.ensure_image_built(plugin_dir)

    (plugin_dir / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    inspected: list[str] = []
    monkeypatch.setattr(
        cb, "_image_exists", lambda tag: (inspected.append(tag), False)[1]
    )
    second = cb.ensure_image_built(plugin_dir)

    assert first != second
    assert inspected  # the changed directory's new tag was actually checked


def test_docker_build_failure_raises_container_build_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(argv, capture_output, text):
        return subprocess.CompletedProcess(argv, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ContainerBuildError, match="boom"):
        cb._docker_build(tmp_path, "civex-plugin-example:abc123")


def test_missing_docker_binary_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, capture_output, text):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ConfigError, match="docker"):
        cb._image_exists("civex-plugin-example:abc123")
