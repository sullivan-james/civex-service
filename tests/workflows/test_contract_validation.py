"""Save-time and run-time validation of a workflow against the contracts its
plugins declared in `describe` (CIVEX-142).

Written against the real built-in registrations rather than fakes: the point
of the story is that one declaration drives validation for every tier, so
these assert the errors a workflow author actually gets for the plugins they
actually use.
"""

from __future__ import annotations

import pytest
import yaml

from civex.plugins.registry import all_plugins
from civex.workflows.contract_validation import validate_workflow_contracts
from civex.workflows.definition import WorkflowDef


def _errors(yaml_text: str) -> list[str]:
    """Message text only -- most of this file cares about wording, not the
    `step` field. See test_*_error_is_tagged_with_its_step below for that."""
    wf = WorkflowDef.model_validate(yaml.safe_load(yaml_text))
    return [e.message for e in validate_workflow_contracts(wf, all_plugins())]


def test_valid_workflow_has_no_contract_errors():
    assert (
        _errors("""
name: csv-import
steps:
  - id: parse
    plugin: civex.table@1
    config: {field: attachment}
  - id: store
    plugin: civex.save_records@1
    config: {schema: Sample, match_on: [sample_id]}
    inputs: {rows: parse.table}
""")
        == []
    )


def test_unknown_plugin_is_reported():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.does_not_exist
""")
    assert errors == ["Step 'one' references unknown plugin 'civex.does_not_exist'"]


def test_typo_in_config_key_is_rejected():
    """The single most valuable check here: an unrecognized config key is
    silently ignored by Pydantic, so before this the step just quietly did
    nothing at run time."""
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {fileds: subject}
""")
    assert any("unknown key 'fileds'" in e for e in errors)
    assert any("accepts: date_format, field, output_type, pattern" in e for e in errors)


def test_missing_required_config_key_is_rejected():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.save_records@1
    config: {}
""")
    assert errors == ["Step 'one' config: 'schema' is a required property"]


def test_config_value_of_wrong_type_is_rejected():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {field: 42}
""")
    assert errors == ["Step 'one' config: field: 42 is not of type 'string'"]


def test_config_key_declared_by_alias_is_accepted():
    """Several built-ins declare `schema` as a Pydantic alias for
    schema_name; the JSON Schema names the alias, which is what the YAML
    uses."""
    assert (
        _errors("""
name: wf
steps:
  - id: one
    plugin: civex.save_records@1
    config: {schema: Sample}
    inputs: {rows: __input__.rows}
inputs:
  rows: {type: value}
""")
        == []
    )


def test_unknown_input_name_is_rejected():
    errors = _errors("""
name: wf
steps:
  - id: get
    plugin: civex.value_from_filename@1
    config: {field: a}
  - id: save
    plugin: civex.set_fields@1
    config: {field: b}
    inputs: {valeu: get.value}
""")
    assert any("supplies unknown input 'valeu'" in e for e in errors)


def test_reference_to_an_output_the_upstream_step_does_not_produce():
    """save_field declares no outputs at all, so referencing one is
    catchable -- this is why an empty declaration has to mean something
    different from an absent one."""
    errors = _errors("""
name: wf
steps:
  - id: save
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: __input__.v}
  - id: after
    plugin: civex.set_fields@1
    config: {field: b}
    inputs: {value: save.result}
inputs:
  v: {type: value}
""")
    assert errors == [
        "Step 'after' input 'value' references 'save.result', but step 'save' "
        "(civex.set_fields@1) produces no output 'result' (produces: none)"
    ]


def test_reference_to_unknown_step_is_reported():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: nope.value}
""")
    assert errors == ["Step 'one' input 'value' references unknown step 'nope'"]


def test_reference_without_an_output_name_is_reported():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: justastep}
""")
    assert errors == [
        "Step 'one' input 'value' must reference 'step_id.output_name', got 'justastep'"
    ]


def test_manual_run_input_must_be_declared_by_the_workflow():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: __input__.missing}
inputs:
  present: {type: value}
""")
    assert errors == [
        "Step 'one' input 'value' references '__input__.missing', but the "
        "workflow declares no input 'missing' (has: present)"
    ]


def test_declared_manual_run_input_is_accepted():
    assert (
        _errors("""
name: wf
steps:
  - id: one
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: __input__.present}
inputs:
  present: {type: value}
""")
        == []
    )


def test_duplicate_step_ids_are_reported():
    """The executor keys steps by id, so a duplicate silently drops one
    rather than running it."""
    errors = _errors("""
name: wf
steps:
  - id: same
    plugin: civex.value_from_filename@1
    config: {field: a}
  - id: same
    plugin: civex.value_from_filename@1
    config: {field: b}
""")
    assert errors == ["Step id 'same' is used more than once"]


def test_all_violations_are_reported_together():
    """Whoever is fixing these -- often the AI's save_workflow tool -- would
    otherwise have to resubmit once per error."""
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.save_records@1
    config: {}
  - id: two
    plugin: civex.nope
  - id: three
    plugin: civex.set_fields@1
    config: {field: x}
    inputs: {valeu: one.created}
""")
    assert len(errors) == 3


def test_valid_if_condition_has_no_errors():
    assert (
        _errors("""
name: wf
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {field: a}
  - id: two
    plugin: civex.set_fields@1
    config: {field: b}
    inputs: {value: __input__.v}
    if: one.value == 'x'
inputs:
  v: {type: value}
""")
        == []
    )


def test_if_referencing_unknown_step_is_reported():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: __input__.v}
    if: nope.value
inputs:
  v: {type: value}
""")
    assert errors == ["Step 'one' 'if' references unknown step 'nope'"]


def test_if_referencing_undeclared_workflow_input_is_reported():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: __input__.v}
    if: __input__.missing
inputs:
  v: {type: value}
""")
    assert errors == [
        "Step 'one' 'if' references '__input__.missing', but the workflow "
        "declares no input 'missing' (has: v)"
    ]


def test_if_referencing_an_output_the_upstream_step_does_not_produce():
    errors = _errors("""
name: wf
steps:
  - id: save
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: __input__.v}
  - id: after
    plugin: civex.set_fields@1
    config: {field: b}
    inputs: {value: __input__.v}
    if: save.result == 1
inputs:
  v: {type: value}
""")
    assert errors == [
        "Step 'after' 'if' references 'save.result', but step 'save' "
        "(civex.set_fields@1) produces no output 'result' (produces: none)"
    ]


def test_unsafe_if_expression_is_rejected():
    errors = _errors("""
name: wf
steps:
  - id: one
    plugin: civex.set_fields@1
    config: {field: a}
    inputs: {value: __input__.v}
    if: one.value + 1
inputs:
  v: {type: value}
""")
    assert len(errors) == 1
    assert "Step 'one' 'if':" in errors[0]


def test_plugin_declaring_no_input_contract_is_not_input_checked(monkeypatch):
    """A plugin that hasn't declared inputs/outputs (None, the PluginBase
    default) opts out of name checking rather than making every workflow
    using it unsaveable."""
    import dataclasses

    registration = all_plugins()["civex.value_from_filename@1"]
    undeclared = dataclasses.replace(registration, inputs=None, outputs=None)
    plugins = {**all_plugins(), "civex.value_from_filename@1": undeclared}

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {field: a}
  - id: two
    plugin: civex.value_from_filename@1
    config: {field: b}
    inputs: {anything_at_all: one.whatever}
""")
    )
    assert validate_workflow_contracts(wf, plugins) == []


def test_undeclared_contract_does_not_exempt_config_validation(monkeypatch):
    """Opting out of input/output declarations is not opting out of config
    validation -- every plugin has a Config model."""
    import dataclasses

    registration = all_plugins()["civex.value_from_filename@1"]
    undeclared = dataclasses.replace(registration, inputs=None, outputs=None)

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {nonsense: 1}
""")
    )
    errors = validate_workflow_contracts(
        wf, {"civex.value_from_filename@1": undeclared}
    )
    assert any("unknown key 'nonsense'" in e.message for e in errors)


def test_save_rejects_a_workflow_that_violates_a_contract(ctx):
    from civex.domain.exceptions import ValidationError, WorkflowValidationError

    with pytest.raises(ValidationError) as excinfo:
        ctx.workflow_svc.save(
            "broken",
            """
name: broken
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {field: subject, fileds: subject}
""",
        )
    assert "unknown key 'fileds'" in str(excinfo.value)
    assert ctx.workflow_svc.find_path("broken") is None

    assert isinstance(excinfo.value, WorkflowValidationError)
    assert excinfo.value.errors == [
        {
            "step": "one",
            "message": (
                "Step 'one' config has unknown key 'fileds' for plugin "
                "'civex.value_from_filename@1' (accepts: date_format, field, output_type, pattern)"
            ),
        }
    ]


def test_contract_errors_are_tagged_with_their_step():
    """The `step` field is what lets a caller (the workflows API, CIVEX-109)
    point a user at the offending step without parsing it back out of the
    message text."""
    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {}
  - id: two
    plugin: civex.nope
""")
    )
    errors = validate_workflow_contracts(wf, all_plugins())
    assert {e.step for e in errors} == {"one", "two"}


def test_run_revalidates_before_executing_any_step(
    ctx, make_collection, make_schema, make_record
):
    """A workflow saved when its plugin's contract fit can still be wrong by
    the time it runs -- the plugin may have been edited since. Failing before
    step one means no half-finished record writes to unpick."""
    from civex.plugins.base import WorkflowContext
    from civex.workflows import executor

    dataset = make_collection("study")
    make_schema("subject", fields=[("name", "string")])
    record = make_record("study", "subject", {"name": "S01"})

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: one
    plugin: civex.value_from_filename@1
    config: {no_such_key: x}
""")
    )
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)

    with pytest.raises(ValueError) as excinfo:
        executor.run(wf, wf_ctx, all_plugins())
    assert "no longer matches its plugins' declared contracts" in str(excinfo.value)
