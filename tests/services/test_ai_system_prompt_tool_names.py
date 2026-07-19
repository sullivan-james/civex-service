"""Golden test (CIVEX-62): every tool name referenced in
_build_system_prompt's "MANDATORY tool-use rules" section must exist in
TOOL_REGISTRY.

Guards against the same kind of drift CIVEX-50/53 fixed for provider/model
config: this section is hand-written prose, not derived from the registry,
so if a tool is renamed or removed but the prompt text isn't updated to
match, the assistant would be instructed to call a tool that doesn't exist.
"""

from __future__ import annotations

import re

from civex.services.ai.service import _build_system_prompt
from civex.services.ai.tools.registry import TOOL_REGISTRY

# Every current tool name follows verb_noun[_noun...] (list_schemas,
# create_record, add_schema_field, ...) -- matches real tool-name
# references while staying unlikely to match ordinary prose.
_TOOL_NAME_RE = re.compile(
    r"\b(?:list|get|save|create|update|delete|query|add)_[a-z][a-z_]*\b"
)


class _FakeSchemaSvc:
    def list_all(self):
        return []


class _FakeDatasetSvc:
    def list_all(self):
        return []


class _FakeCtx:
    schema_svc = _FakeSchemaSvc()
    dataset_svc = _FakeDatasetSvc()


def _mandatory_rules_section() -> str:
    prompt = _build_system_prompt(_FakeCtx())
    start = prompt.index("## MANDATORY tool-use rules")
    rest = prompt[start:]
    next_heading = rest.index("\n## ", 1)
    return rest[:next_heading]


def test_every_tool_referenced_in_mandatory_rules_exists_in_registry() -> None:
    section = _mandatory_rules_section()
    referenced = set(_TOOL_NAME_RE.findall(section))
    assert referenced  # sanity: the section does reference tools at all
    missing = referenced - set(TOOL_REGISTRY)
    assert not missing, (
        f"MANDATORY tool-use rules references unknown tool(s): {missing}"
    )


def test_referenced_tools_include_the_ones_the_numbered_rules_are_about() -> None:
    """Not exhaustive, but pins the section to still reference the specific
    tools its numbered rules are actually written about -- catches a rule
    being edited to talk about the wrong tool name entirely, which the
    "exists in TOOL_REGISTRY" check above wouldn't catch on its own."""
    section = _mandatory_rules_section()
    for name in [
        "list_workflows",
        "list_schemas",
        "list_plugins",
        "get_workflow_authoring_guide",
        "save_workflow",
        "save_plugin",
        "create_schema",
        "add_schema_field",
        "update_schema_field",
        "list_records",
        "query_records",
        "update_record",
        "delete_record",
    ]:
        assert name in section, f"expected {name!r} to be referenced in the section"
