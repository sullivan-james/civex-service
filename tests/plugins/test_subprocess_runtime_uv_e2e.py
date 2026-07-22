"""One real end-to-end path through describe_plugin()/run_plugin(): actually
spawns `uv run --no-project`, resolving `civex-plugin-sdk` via the
--find-links-a-locally-built-wheel mechanism (civex-plugin-sdk isn't
published to PyPI yet -- see subprocess_runtime._sdk_find_links_dir). Every
other subprocess_runtime test bypasses uv entirely (spawns a plain
sys.executable child instead) for speed -- this is the one test that proves
the actual `uv run` command construction / dependency resolution works, not
just the mocked dispatch logic. Skipped if `uv` isn't on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from civex.plugins.base import PluginTier
from civex.plugins.registry import discover_user_plugins, get_plugin

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is not installed on PATH"
)

_UV_PLUGIN_CODE = """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.uv_e2e_plugin"
    name = "UV E2E Plugin"
    capabilities = ["commit"]

    class Config(BaseModel):
        greeting: str = "hi"

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        if inputs.get("call_commit"):
            ctx.commit()
        return {"greeting": config.greeting}

if __name__ == "__main__":
    serve(Plugin)
"""


def test_real_uv_run_discovers_and_executes_a_plugin(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "uv_e2e_plugin.py").write_text(_UV_PLUGIN_CODE)

    discover_user_plugins(plugins_dir)

    registration = get_plugin("project.uv_e2e_plugin")
    assert registration is not None
    assert registration.tier == PluginTier.SUBPROCESS
    assert registration.capabilities == ["commit"]

    class _FakeCtx:
        def __init__(self) -> None:
            self.committed = False

        def commit(self) -> None:
            self.committed = True

    ctx = _FakeCtx()
    result = registration.invoke(
        {"call_commit": True},
        registration.config_model(greeting="hello"),
        ctx,
        30.0,
    )
    assert result.outputs == {"greeting": "hello"}
    assert ctx.committed is True
