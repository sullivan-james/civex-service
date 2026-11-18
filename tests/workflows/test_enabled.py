"""`set_enabled_text` changes one line and keeps everything else."""

from __future__ import annotations

import yaml

from civex.workflows.definition import WorkflowDef, set_enabled_text

_BASE = """\
# A comment people wrote
name: >
  A folded
  name
steps: []  # none yet
"""


def _parsed(text: str) -> WorkflowDef:
    return WorkflowDef.model_validate(yaml.safe_load(text))


def test_a_file_without_the_key_is_on() -> None:
    assert _parsed(_BASE).enabled is True


def test_the_key_goes_before_name_and_comments_stay() -> None:
    off = set_enabled_text(_BASE, False)
    assert off == "# A comment people wrote\nenabled: false\n" + _BASE.split("\n", 1)[1]
    assert _parsed(off).enabled is False
    assert _parsed(off).name == "A folded name\n"


def test_an_existing_key_is_replaced_not_repeated() -> None:
    on = set_enabled_text(set_enabled_text(_BASE, False), True)
    assert on.count("enabled:") == 1
    assert _parsed(on).enabled is True
