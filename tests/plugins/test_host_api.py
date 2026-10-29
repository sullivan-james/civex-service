"""The one table of what a plugin may ask of civex (`civex.plugins.host_api`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from civex.domain.exceptions import CapabilityDeniedError, PluginExecutionError
from civex.plugins import host_api
from civex.plugins.host_api import HOST_API, PLUGIN_ACTIONS, granted

DOCS = (
    Path(__file__).resolve().parents[2] / "docs" / "extending" / "writing-a-plugin.md"
)


def test_an_action_grants_every_function_that_needs_it() -> None:
    allowed = granted(["read"])
    assert {"get_record", "find_records", "get_file", "list_schemas"} <= allowed
    assert "update_record" not in allowed and "delete_record" not in allowed


def test_a_function_name_grants_just_that_function() -> None:
    allowed = granted(["find_records"])
    assert "find_records" in allowed
    assert "get_record" not in allowed


def test_functions_needing_no_grant_are_always_allowed() -> None:
    assert "commit" in granted([])


def test_every_function_needs_an_action_a_plugin_may_be_given() -> None:
    for fn in HOST_API.values():
        assert fn.action is None or fn.action in PLUGIN_ACTIONS, fn.name


def test_unknown_capabilities_are_named() -> None:
    assert host_api.unknown_capabilities(["read", "find_records", "fly"]) == ["fly"]


def test_a_refusal_says_what_to_add() -> None:
    with pytest.raises(
        CapabilityDeniedError, match="add 'delete' \\(or 'delete_record'\\)"
    ):
        host_api.dispatch(None, granted(["read"]), "delete_record", {}, None)  # type: ignore[arg-type]


def test_an_unknown_function_is_an_error_not_a_refusal() -> None:
    with pytest.raises(PluginExecutionError, match="unknown host function"):
        host_api.dispatch(None, granted(["read"]), "fly", {}, None)  # type: ignore[arg-type]


def test_the_docs_list_every_function_a_plugin_can_call() -> None:
    """writing-a-plugin.md's table of ctx methods is held to the table."""
    text = DOCS.read_text(encoding="utf-8")
    documented = set(re.findall(r"`ctx\.(\w+)\(", text))
    callable_ = {name for name in HOST_API if name != "commit"}
    assert callable_ - documented == set(), "add these to writing-a-plugin.md"
