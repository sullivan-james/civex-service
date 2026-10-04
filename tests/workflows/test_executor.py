"""workflows/executor.py's timeout resolution (CIVEX-137): a step's own
`timeout:` overrides the workflow-run's default_timeout_seconds, which
itself defaults to 60.0 when the caller doesn't pass one.

Also covers conditional step execution (CIVEX-129): a step whose `if:`
evaluates falsy is never dispatched, and produces a SKIPPED marker for any
downstream step referencing its outputs.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from civex.plugins.base import PluginTier, StepResult
from civex.plugins.registry import PluginRegistration
from civex.workflows import executor
from civex.workflows.conditions import SKIPPED
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
        inputs=None,
        outputs=None,
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


def test_step_with_falsy_if_is_not_invoked() -> None:
    seen: list[float] = []
    wf = WorkflowDef(
        name="wf",
        steps=[StepDef(id="s1", plugin="test.plugin", **{"if": "1 == 2"})],
    )
    executor.run(wf, _FakeCtx(), {"test.plugin": _recording_registration(seen)})
    assert seen == []


def test_step_with_truthy_if_is_invoked() -> None:
    seen: list[float] = []
    wf = WorkflowDef(
        name="wf",
        steps=[StepDef(id="s1", plugin="test.plugin", **{"if": "1 == 1"})],
    )
    executor.run(wf, _FakeCtx(), {"test.plugin": _recording_registration(seen)})
    assert seen == [60.0]


def test_downstream_step_sees_skipped_marker_for_a_skipped_step() -> None:
    seen: list[float] = []
    captured: dict = {}

    def invoke_capturing(inputs, config, ctx, timeout) -> StepResult:
        captured.update(inputs)
        return StepResult(outputs={})

    registrations = {
        "test.plugin": _recording_registration(seen),
        "test.capture": PluginRegistration(
            id="test.capture",
            name="Capture",
            category="general",
            tier=PluginTier.SUBPROCESS,
            capabilities=[],
            description="",
            inputs=None,
            outputs=None,
            config_model=_EmptyConfig,
            module_name="test",
            invoke=invoke_capturing,
        ),
    }
    wf = WorkflowDef(
        name="wf",
        steps=[
            StepDef(id="s1", plugin="test.plugin", **{"if": "1 == 2"}),
            StepDef(
                id="s2",
                plugin="test.capture",
                inputs={"value": "s1.ok"},
            ),
        ],
    )
    executor.run(wf, _FakeCtx(), registrations)
    assert seen == []
    assert captured == {"value": SKIPPED}


def test_step_if_referencing_unrun_step_raises() -> None:
    wf = WorkflowDef(
        name="wf",
        steps=[StepDef(id="s1", plugin="test.plugin", **{"if": "nope.value"})],
    )
    with pytest.raises(ValueError, match="unknown step 'nope'"):
        executor.run(wf, _FakeCtx(), {"test.plugin": _recording_registration([])})


# -- stopping a run (the kill switch) ---------------------------------------------


def test_a_run_told_to_stop_ends_before_its_next_step() -> None:
    from civex.domain.exceptions import JobCancelled

    seen: list[float] = []
    wf = WorkflowDef(
        name="wf",
        steps=[
            StepDef(id="s1", plugin="test.plugin"),
            StepDef(id="s2", plugin="test.plugin", inputs={"x": "s1.ok"}),
            StepDef(id="s3", plugin="test.plugin", inputs={"x": "s2.ok"}),
        ],
    )
    asked: list[int] = []

    def stop_after_the_first_step() -> bool:
        asked.append(len(seen))
        return len(seen) >= 1

    with pytest.raises(JobCancelled, match="before step 's2'") as stopped:
        executor.run(
            wf,
            _FakeCtx(),
            {"test.plugin": _recording_registration(seen)},
            should_stop=stop_after_the_first_step,
        )

    assert len(seen) == 1  # only the first step ran
    # What had been done is kept for the run's record, as for a failure.
    steps = stopped.value.step_executions  # type: ignore[attr-defined]
    assert [s["step_id"] for s in steps] == ["s1"]
    assert asked == [0, 1]  # asked before every step that was reached


def test_a_run_that_is_not_told_to_stop_runs_to_the_end() -> None:
    seen: list[float] = []
    wf = WorkflowDef(
        name="wf",
        steps=[
            StepDef(id="s1", plugin="test.plugin"),
            StepDef(id="s2", plugin="test.plugin", inputs={"x": "s1.ok"}),
        ],
    )
    executor.run(
        wf,
        _FakeCtx(),
        {"test.plugin": _recording_registration(seen)},
        should_stop=lambda: False,
    )
    assert len(seen) == 2
