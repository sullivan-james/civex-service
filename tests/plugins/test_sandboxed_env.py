"""The plugin subprocess gets a minimal environment, but on Windows it must
include the variables uv needs to find the user's Python installs."""

from __future__ import annotations

import sys

import pytest

from civex.plugins.subprocess_runtime import sandboxed_env


def test_secrets_are_not_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVEX_DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    env = sandboxed_env()
    assert "CIVEX_DATABASE_URL" not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_uv_python_choice_and_proxy_are_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UV_PYTHON", "/opt/py/bin/python")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
    env = sandboxed_env()
    assert env["UV_PYTHON"] == "/opt/py/bin/python"
    assert env["HTTPS_PROXY"] == "http://proxy:3128"


def test_windows_gets_localappdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\\Users\\a\\AppData\\Local")
    assert sandboxed_env()["LOCALAPPDATA"] == r"C:\\Users\\a\\AppData\\Local"
