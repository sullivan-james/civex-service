"""Every tier is a launcher (`civex.plugins.launchers`), and every plugin is
run by the same `runtime`. These cover what is particular to each: a
built-in runs in this process through the protocol and its checks; a
container is started per request."""

from __future__ import annotations

import time
from typing import Any

import pytest
from pydantic import BaseModel

from civex_plugin_sdk import Ctx, Plugin

from civex.domain.exceptions import PluginExecutionError
from civex.plugins import runtime, workers
from civex.plugins.base import PluginTier
from civex.plugins.launchers import DockerLauncher, InProcessLauncher


class _Ctx:
    """The host side of a run: just enough of a WorkflowContext."""

    def __init__(self) -> None:
        self.patched: list[tuple[str, dict]] = []

    def get_context_record(self):
        class R:
            def to_dict(self) -> dict:
                return {"id": "r1", "data": {"n": 2}}

        return R()

    def patch_record(self, record_id: str, fields: dict):
        self.patched.append((record_id, fields))

        class R:
            def to_dict(self) -> dict:
                return {"id": record_id, "data": fields}

        return R()


class Doubler(Plugin):
    id = "test.doubler"
    name = "Doubler"
    capabilities = ["read", "write_records"]

    class Config(BaseModel):
        pass

    def invoke(self, inputs: dict[str, Any], config, ctx: Ctx) -> dict[str, Any]:
        record = ctx.get_context_record()
        ctx.patch_record(record["id"], {"n": record["data"]["n"] * 2})
        return {"thread": __import__("threading").current_thread().name}


class Sneaky(Doubler):
    id = "test.sneaky"
    capabilities = ["read"]  # writes without being allowed to


class Slow(Plugin):
    id = "test.slow"
    name = "Slow"

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict[str, Any]:
        time.sleep(0.5)
        return {"done": True}


def _run(cls: type[Plugin], ctx: Any = None, timeout: float = 20.0) -> dict:
    ctx = ctx or _Ctx()
    return runtime.run(
        InProcessLauncher(cls), {}, {}, ctx, list(cls.capabilities), timeout
    ).outputs


def test_a_builtin_runs_in_this_process_through_the_host_functions() -> None:
    ctx = _Ctx()
    outputs = _run(Doubler, ctx)
    assert outputs["thread"] == "civex-plugin-test.doubler"
    assert ctx.patched == [("r1", {"n": 4})]


def test_a_builtin_is_held_to_its_capabilities_like_any_plugin() -> None:
    with pytest.raises(PluginExecutionError) as e:
        _run(Sneaky)
    assert e.value.kind == "capability_denied"


def test_a_builtin_thread_is_kept_between_runs() -> None:
    _run(Doubler)
    _run(Doubler)
    assert workers.POOL.idle_count() == 1


def test_a_builtin_is_not_stopped_by_a_step_timeout() -> None:
    """A thread can't be killed, and built-ins always ran to the end."""
    assert _run(Slow, timeout=0.05) == {"done": True}


def test_a_container_is_started_for_each_request_not_kept() -> None:
    launcher = DockerLauncher("img")
    assert launcher.reusable is False
    assert launcher.tier is PluginTier.CONTAINER
    assert launcher.key == ("docker", "img", None, None)
