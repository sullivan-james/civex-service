"""PluginService: single source of truth for plugin file I/O, extracted from
server/routers/plugins.py (CIVEX-54). No prior test coverage existed for the
router this replaces -- these tests cover the behavior for the first time.
"""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError

_VALID_CODE = """\
from civex.plugins.base import BasePlugin, WorkflowContext

class Plugin(BasePlugin):
    id = "project.my_plugin"
    name = "My Plugin"

    def run(self, inputs, config, ctx: WorkflowContext) -> dict:
        return {}
"""


def test_list_registered_includes_builtins(ctx: AppContext) -> None:
    registered = ctx.plugin_svc.list_registered()
    ids = {p["id"] for p in registered}
    assert any(pid.startswith("civex.") for pid in ids)
    assert all(p["builtin"] for p in registered if p["id"].startswith("civex."))


def test_list_registered_includes_category_and_config_schema(
    ctx: AppContext,
) -> None:
    """category/config_schema are introspected off each plugin's own class
    (BasePlugin.category, BasePlugin.Config) rather than hand-maintained,
    so they can't silently drift from the real plugin (CIVEX-56)."""
    registered = {p["id"]: p for p in ctx.plugin_svc.list_registered()}
    builtin = next(p for pid, p in registered.items() if pid.startswith("civex."))
    assert isinstance(builtin["category"], str) and builtin["category"]
    assert builtin["config_schema"]["type"] == "object"
    assert "properties" in builtin["config_schema"]


def test_list_raw_empty_when_no_plugins_dir_populated(ctx: AppContext) -> None:
    assert ctx.plugin_svc.list_raw() == []


def test_save_then_list_raw_returns_full_source(ctx: AppContext) -> None:
    ctx.plugin_svc.save("my_plugin", _VALID_CODE)
    raw = ctx.plugin_svc.list_raw()
    assert raw == [{"filename": "my_plugin.py", "code": _VALID_CODE}]


def test_save_registers_the_plugin_immediately(ctx: AppContext) -> None:
    ctx.plugin_svc.save("my_plugin", _VALID_CODE)
    registered = ctx.plugin_svc.list_registered()
    assert any(p["id"] == "project.my_plugin" for p in registered)


def test_validate_rejects_bad_name(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="lowercase letters"):
        ctx.plugin_svc.validate("BadName", _VALID_CODE)


def test_validate_rejects_syntax_error(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="Syntax error"):
        ctx.plugin_svc.validate("my_plugin", "def broken(:")


def test_validate_rejects_missing_plugin_class(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="class named 'Plugin'"):
        ctx.plugin_svc.validate("my_plugin", "x = 1")


def test_validate_does_not_write_anything(ctx: AppContext) -> None:
    ctx.plugin_svc.validate("my_plugin", _VALID_CODE)
    assert ctx.plugin_svc.list_raw() == []


def test_save_rejects_bad_name_without_writing(ctx: AppContext) -> None:
    with pytest.raises(ValidationError):
        ctx.plugin_svc.save("BadName", _VALID_CODE)
    assert ctx.plugin_svc.list_raw() == []


def test_save_uploaded_writes_and_returns_plugin_id(ctx: AppContext) -> None:
    plugin_id = ctx.plugin_svc.save_uploaded("my_plugin.py", _VALID_CODE.encode())
    assert plugin_id == "project.my_plugin"
    assert ctx.plugin_svc.list_raw() == [
        {"filename": "my_plugin.py", "code": _VALID_CODE}
    ]
