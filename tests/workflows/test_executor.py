"""workflows/executor.py's timeout resolution (CIVEX-137): a step's own
`timeout:` overrides the workflow-run's default_timeout_seconds, which
itself defaults to 60.0 when the caller doesn't pass one.
"""

from __future__ import annotations

from pydantic import BaseModel

from civex.plugins.base import PluginTier, StepResult
from civex.plugins.registry import PluginRegistration
from civex.workflows import executor
from civex.workflows.definition import StepDef, WorkflowDef


class _EmptyConfig(BaseModel):
    pass


class _FakeCtx:
    def __init__(self) -> None:
        self.committed = False
        self.record = type("R", (), {"id": "rec-1"})()

    def commit(self) -> None:
        self.committed = True


def _recording_registration(seen_timeouts: list[float]) -> PluginRegistration:
    def invoke(inputs, config, ctx, timeout) -> StepResult:
        seen_timeouts.append(timeout)
        return StepResult(outputs={"ok": True})

    return PluginRegistration(
        id="test.plugin",
        name="Test",
        category="general",
        tier=PluginTier.SUBPROCESS,
        capabilities=[],
        description="",
        config_model=_EmptyConfig,
        module_name="test",
        invoke=invoke,
    )


def test_step_uses_default_timeout_seconds_when_not_overridden() -> None:
    seen: list[float] = []
    wf = WorkflowDef(
        name="wf",
        steps=[StepDef(id="s1", plugin="test.plugin")],
    )
    executor.run(
        wf,
        _FakeCtx(),
        {"test.plugin": _recording_registration(seen)},
        default_timeout_seconds=45.0,
    )
    assert seen == [45.0]


def test_step_timeout_overrides_default() -> None:
    seen: list[float] = []
    wf = WorkflowDef(
        name="wf",
        steps=[StepDef(id="s1", plugin="test.plugin", timeout=5)],
    )
    executor.run(
        wf,
        _FakeCtx(),
        {"test.plugin": _recording_registration(seen)},
        default_timeout_seconds=45.0,
    )
    assert seen == [5]


def test_default_timeout_seconds_falls_back_to_sixty() -> None:
    seen: list[float] = []
    wf = WorkflowDef(name="wf", steps=[StepDef(id="s1", plugin="test.plugin")])
    executor.run(wf, _FakeCtx(), {"test.plugin": _recording_registration(seen)})
    assert seen == [60.0]
