"""civex record set: the same bulk edit as the API, from a terminal."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.context import build_local_context
from civex.config import load_config
from civex.main import app

runner = CliRunner()


def _setup() -> list[str]:
    for args in (
        ["schema", "create", "trial"],
        ["schema", "add-field", "trial", "subject", "--type", "string"],
        ["schema", "add-field", "trial", "dose", "--type", "integer"],
        ["collection", "create", "study"],
    ):
        assert runner.invoke(app, args).exit_code == 0, args
    ids = []
    for subject in ("a", "b"):
        result = runner.invoke(
            app,
            ["record", "add", "--to", "study", "--schema", "trial"],
            input=f"{subject}\n\n",
        )
        assert result.exit_code == 0, result.output
        ids.append(result.output.split("Added record ")[1].split(".")[0].strip())
    return ids


def _doses() -> list:
    ctx = build_local_context(load_config())
    try:
        return sorted(
            (r.data.get("dose") for r in ctx.record_svc.find("study", "trial")),
            key=str,
        )
    finally:
        ctx.close()


def test_set_shows_the_plan_and_types_each_value(project_dir: Path) -> None:
    a, b = _setup()
    result = runner.invoke(
        app, ["record", "set", "dose=3", "--id", a[:8], "--id", b, "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "2 would change" in result.output
    assert _doses() == [None, None]

    result = runner.invoke(app, ["record", "set", "dose=3", "--id", a, "--id", b, "-y"])
    assert result.exit_code == 0, result.output
    assert "Changed 2 record(s)" in result.output
    assert _doses() == [3, 3]  # integers, not "3"


def test_set_over_a_query_and_clearing(project_dir: Path) -> None:
    _setup()
    result = runner.invoke(
        app, ["record", "set", "dose=", "--in", "study", "--schema", "trial", "-y"]
    )
    assert result.exit_code == 0, result.output
    assert "0 would change" in result.output  # already empty

    result = runner.invoke(
        app,
        ["record", "set", "dose=7", "--in", "study", "-s", "trial", "-w", "subject=a"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert _doses() == [7, None]


def test_set_refuses_a_bad_value_or_an_unknown_field(project_dir: Path) -> None:
    a, _ = _setup()
    result = runner.invoke(app, ["record", "set", "dose=lots", "--id", a, "-y"])
    assert result.exit_code == 1
    result = runner.invoke(app, ["record", "set", "nope=1", "--id", a, "-y"])
    assert result.exit_code == 1 and "no field 'nope'" in result.output
    result = runner.invoke(app, ["record", "set", "dose=1", "-y"])
    assert result.exit_code == 1
