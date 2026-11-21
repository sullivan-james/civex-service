"""`civex schema add-field --type formula`, `update-field --expression` and
`civex schema preview-formula`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.config import load_config
from civex.context import build_local_context
from civex.main import app

runner = CliRunner()


def _setup() -> None:
    ctx = build_local_context(load_config())
    ctx.schema_svc.create("patient")
    ctx.schema_svc.add_field("patient", "mass", "float")
    ctx.schema_svc.add_field("patient", "height", "float")
    ctx.dataset_svc.create("study")
    ctx.record_svc.add("study", "patient", {"mass": 81.0, "height": 1.8})
    ctx.commit()
    ctx.close()


def _field(name: str):
    ctx = build_local_context(load_config())
    try:
        return next(f for f in ctx.schema_svc.get("patient").fields if f.name == name)
    finally:
        ctx.close()


def test_add_and_change_a_formula_field(project_dir: Path) -> None:
    _setup()
    added = runner.invoke(
        app,
        [
            "schema",
            "add-field",
            "patient",
            "bmi",
            "--type",
            "formula",
            "--expression",
            "mass / height ** 2",
            "--decimals",
            "1",
        ],
    )
    assert added.exit_code == 0, added.output
    bmi = _field("bmi")
    assert bmi.restrictions == {
        "expression": "mass / height ** 2",
        "decimals": 1,
        "result": "float",
    }

    changed = runner.invoke(
        app,
        ["schema", "update-field", "patient", "bmi", "--expression", "mass / height"],
    )
    assert changed.exit_code == 0, changed.output
    assert _field("bmi").restrictions["expression"] == "mass / height"

    bad = runner.invoke(
        app,
        ["schema", "add-field", "patient", "x", "--type", "formula", "-e", "nope * 2"],
    )
    assert bad.exit_code == 1 and "nope" in bad.output
    wrong_type = runner.invoke(
        app,
        ["schema", "add-field", "patient", "y", "--type", "float", "-e", "mass"],
    )
    assert wrong_type.exit_code == 1 and "--type formula" in wrong_type.output


def test_preview_a_formula(project_dir: Path) -> None:
    _setup()
    shown = runner.invoke(
        app, ["schema", "preview-formula", "patient", "round(mass / height ** 2, 1)"]
    )
    assert shown.exit_code == 0, shown.output
    assert "25.0" in shown.output and "float" in shown.output

    broken = runner.invoke(app, ["schema", "preview-formula", "patient", "mass / 0"])
    assert broken.exit_code == 0 and "divided by zero" in broken.output

    refused = runner.invoke(app, ["schema", "preview-formula", "patient", "nope"])
    assert refused.exit_code == 1 and "nope" in refused.output
