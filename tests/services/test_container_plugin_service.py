"""ContainerPluginService: Tier 2 (container) plugin file management --
list plugin directories, read/write their files, rebuild the Docker image
on save (CIVEX-156)."""

from __future__ import annotations

import subprocess

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError


def _make_container_plugin(ctx: AppContext, name: str = "my_plugin") -> None:
    root = ctx.container_plugin_svc._dir / name
    root.mkdir(parents=True)
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (root / "civex-plugin.toml").write_text(
        'id = "example.my_plugin"\nname = "My Plugin"\n', encoding="utf-8"
    )
    (root / "src").mkdir()
    (root / "src" / "plugin.c").write_text(
        "int main() { return 0; }\n", encoding="utf-8"
    )


def test_list_container_plugins_empty_when_no_plugins_dir(ctx: AppContext) -> None:
    assert ctx.container_plugin_svc.list_container_plugins() == []


def test_list_container_plugins_finds_dockerfile_and_manifest_pair(
    ctx: AppContext,
) -> None:
    _make_container_plugin(ctx)
    result = ctx.container_plugin_svc.list_container_plugins()
    assert result == [
        {
            "name": "my_plugin",
            "files": ["Dockerfile", "civex-plugin.toml", "src/plugin.c"],
        }
    ]


def test_list_container_plugins_ignores_plain_py_plugin_dirs(
    ctx: AppContext,
) -> None:
    plugins_dir = ctx.container_plugin_svc._dir
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "my_py_plugin.py").write_text("class Plugin:\n    pass\n")
    assert ctx.container_plugin_svc.list_container_plugins() == []


def test_get_files_returns_text_contents(ctx: AppContext) -> None:
    _make_container_plugin(ctx)
    files = ctx.container_plugin_svc.get_files("my_plugin")
    assert files["Dockerfile"] == "FROM scratch\n"
    assert files["src/plugin.c"] == "int main() { return 0; }\n"


def test_get_files_skips_binary_files(ctx: AppContext) -> None:
    _make_container_plugin(ctx)
    binary_path = ctx.container_plugin_svc._dir / "my_plugin" / "image.bin"
    binary_path.write_bytes(b"\xff\xfe\x00\x01")
    files = ctx.container_plugin_svc.get_files("my_plugin")
    assert "image.bin" not in files


def test_get_files_raises_not_found_for_unknown_plugin(ctx: AppContext) -> None:
    with pytest.raises(NotFoundError):
        ctx.container_plugin_svc.get_files("nope")


def test_save_file_writes_content(ctx: AppContext) -> None:
    _make_container_plugin(ctx)
    ctx.container_plugin_svc.save_file("my_plugin", "Dockerfile", "FROM alpine\n")
    files = ctx.container_plugin_svc.get_files("my_plugin")
    assert files["Dockerfile"] == "FROM alpine\n"


def test_save_file_creates_new_file(ctx: AppContext) -> None:
    _make_container_plugin(ctx)
    ctx.container_plugin_svc.save_file("my_plugin", "src/extra.c", "// extra\n")
    files = ctx.container_plugin_svc.get_files("my_plugin")
    assert files["src/extra.c"] == "// extra\n"


def test_save_file_rejects_path_traversal(ctx: AppContext) -> None:
    _make_container_plugin(ctx)
    with pytest.raises(ValidationError):
        ctx.container_plugin_svc.save_file("my_plugin", "../../escape.txt", "x")


def test_save_file_raises_not_found_for_unknown_plugin(ctx: AppContext) -> None:
    with pytest.raises(NotFoundError):
        ctx.container_plugin_svc.save_file("nope", "Dockerfile", "FROM scratch\n")


def test_rebuild_reports_failure_when_docker_missing(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docker may or may not be installed wherever tests run, so force the
    FileNotFoundError path explicitly rather than relying on the ambient
    environment lacking a `docker` binary."""
    _make_container_plugin(ctx)

    def fake_run(cmd, capture_output, text, timeout):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(
        "civex.services.container_plugin_service.subprocess.run", fake_run
    )
    result = ctx.container_plugin_svc.rebuild("my_plugin")
    assert result["success"] is False
    assert "docker" in result["log"]


def test_rebuild_reports_success(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_container_plugin(ctx)

    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="built ok\n", stderr=""
        )

    monkeypatch.setattr(
        "civex.services.container_plugin_service.subprocess.run", fake_run
    )
    result = ctx.container_plugin_svc.rebuild("my_plugin")
    assert result == {"success": True, "log": "built ok\n"}


def test_rebuild_reports_nonzero_exit_as_failure(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_container_plugin(ctx)

    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr="build failed\n"
        )

    monkeypatch.setattr(
        "civex.services.container_plugin_service.subprocess.run", fake_run
    )
    result = ctx.container_plugin_svc.rebuild("my_plugin")
    assert result == {"success": False, "log": "build failed\n"}


def test_rebuild_reports_timeout_as_failure(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_container_plugin(ctx)

    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(
        "civex.services.container_plugin_service.subprocess.run", fake_run
    )
    result = ctx.container_plugin_svc.rebuild("my_plugin")
    assert result["success"] is False
    assert "timed out" in result["log"]
