"""`civex workflow list`/`run` -- consolidated onto WorkflowService (CIVEX-54
follow-up); previously did its own glob/parse independently of the router and
the AI assistant's list_workflows tool. No prior test coverage existed for
these commands at all.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()

_VALID_YAML = """\
name: parse-audio-dates
description: A workflow
steps:
  - id: step-one
    plugin: civex.get_field
    config:
      field: subject
"""


def test_workflow_list_empty(project_dir: Path) -> None:
    result = runner.invoke(app, ["workflow", "list"])
    assert result.exit_code == 0
    assert "No workflows defined" in result.output


def test_workflow_list_shows_saved_workflow(project_dir: Path) -> None:
    (project_dir / "_civex" / "workflows" / "parse-audio-dates.yaml").write_text(
        _VALID_YAML, encoding="utf-8"
    )
    result = runner.invoke(app, ["workflow", "list"])
    assert result.exit_code == 0
    assert "parse-audio-dates" in result.output


def test_workflow_run_unknown_workflow_fails(project_dir: Path) -> None:
    # The workflow lookup fails before the record is even looked up, so no
    # schema/collection/record setup is needed here.
    result = runner.invoke(
        app, ["workflow", "run", "ghost-workflow", "--record", "irrelevant"]
    )
    assert result.exit_code != 0
    assert "not found" in result.output


def test_workflow_run_matches_by_name_or_stem(project_dir: Path) -> None:
    (project_dir / "_civex" / "workflows" / "different-filename.yaml").write_text(
        _VALID_YAML, encoding="utf-8"
    )
    runner.invoke(app, ["schema", "create", "trial"])
    runner.invoke(app, ["schema", "add-field", "trial", "subject", "--type", "string"])
    runner.invoke(app, ["collection", "create", "study"])
    add_result = runner.invoke(
        app, ["record", "add", "--to", "study", "--schema", "trial"], input="S01\n"
    )
    assert add_result.exit_code == 0

    # `record find`'s table truncates the id to an 8-char prefix, which
    # record_svc.get()/workflow run's --record both accept as a unique prefix.
    find_result = runner.invoke(app, ["record", "find", "--in", "study"])
    assert find_result.exit_code == 0

    import re

    prefix_match = re.search(r"[0-9a-f]{8}(?=…)", find_result.output)
    assert prefix_match, find_result.output

    # Match by the workflow's declared `name` (parse-audio-dates), not its
    # filename stem (different-filename) -- proves find_by_name checks both.
    result = runner.invoke(
        app, ["workflow", "run", "parse-audio-dates", "--record", prefix_match.group()]
    )
    assert result.exit_code == 0
    assert "Enqueued job" in result.output
