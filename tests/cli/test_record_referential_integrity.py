"""CLI-level coverage for CIVEX-169: `record delete --force` and `doctor`."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()

_RECORD_ID_RE = re.compile(r"record ([0-9a-f-]{36})", re.IGNORECASE)


def _added_id(output: str) -> str:
    match = _RECORD_ID_RE.search(output)
    assert match, output
    return match.group(1)


def _setup_patient_and_visit(project_dir: Path) -> tuple[str, str]:
    runner.invoke(app, ["schema", "create", "patient"])
    runner.invoke(app, ["schema", "create", "visit"])
    runner.invoke(
        app,
        [
            "schema",
            "add-field",
            "visit",
            "patient_ref",
            "--type",
            "reference",
            "--references",
            "patient",
        ],
    )
    runner.invoke(app, ["collection", "create", "study"])

    add_patient = runner.invoke(
        app, ["record", "add", "--to", "study", "--schema", "patient"]
    )
    assert add_patient.exit_code == 0, add_patient.output
    patient_id = _added_id(add_patient.output)

    add_visit = runner.invoke(
        app,
        ["record", "add", "--to", "study", "--schema", "visit"],
        input=f"{patient_id}\n",
    )
    assert add_visit.exit_code == 0, add_visit.output
    visit_id = _added_id(add_visit.output)

    return patient_id, visit_id


def test_record_delete_blocked_by_referrer(project_dir: Path) -> None:
    patient_id, visit_id = _setup_patient_and_visit(project_dir)

    result = runner.invoke(app, ["record", "delete", patient_id, "--yes"])
    assert result.exit_code != 0
    assert "visit" in result.output

    # The record must still be there.
    show = runner.invoke(app, ["record", "show", patient_id])
    assert show.exit_code == 0


def test_record_delete_force_clears_referrer(project_dir: Path) -> None:
    patient_id, visit_id = _setup_patient_and_visit(project_dir)

    result = runner.invoke(app, ["record", "delete", patient_id, "--yes", "--force"])
    assert result.exit_code == 0, result.output

    show = runner.invoke(app, ["record", "show", visit_id])
    assert show.exit_code == 0
    assert "patient_ref" in show.output


def test_doctor_reports_no_issues_on_a_clean_project(project_dir: Path) -> None:
    _setup_patient_and_visit(project_dir)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "No integrity issues found" in result.output
