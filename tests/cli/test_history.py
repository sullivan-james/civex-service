from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from civex.context import AppContext
from civex.main import app

runner = CliRunner()


@pytest.fixture()
def animal(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("animal", fields=[("legs", "integer")])
    make_collection("zoo")
    return make_record("zoo", "animal", {"legs": 4})


def _set_legs(ctx: AppContext, record, legs: int) -> None:
    ctx.record_svc.update(str(record.id), {"legs": legs})
    ctx.commit()


def _entry_for(output: str, action: str) -> str:
    row = next(line for line in output.splitlines() if f" {action} " in f" {line} ")
    match = re.search(r"\b[0-9a-f]{8}\b", row)
    assert match, row
    return match.group(0)


def test_history_lists_shows_and_reverts_an_update(ctx: AppContext, animal) -> None:
    _set_legs(ctx, animal, 3)
    short = str(animal.id)[:8]

    listing = runner.invoke(app, ["history", "record", short])
    assert listing.exit_code == 0, listing.output
    assert "4 → 3" in listing.output

    entry = _entry_for(listing.output, "update")
    shown = runner.invoke(app, ["history", "show", entry])
    assert shown.exit_code == 0, shown.output
    assert "4 → 3" in shown.output

    reverted = runner.invoke(app, ["history", "revert", entry, "--yes"])
    assert reverted.exit_code == 0, reverted.output
    assert "Put back" in reverted.output
    assert ctx.record_svc.get(str(animal.id)).data["legs"] == 4


def test_history_revert_asks_before_changing_anything(ctx: AppContext, animal) -> None:
    _set_legs(ctx, animal, 3)
    listing = runner.invoke(app, ["history", "record", str(animal.id)[:8]])
    entry = _entry_for(listing.output, "update")

    declined = runner.invoke(app, ["history", "revert", entry], input="n\n")
    assert declined.exit_code != 0
    assert ctx.record_svc.get(str(animal.id)).data["legs"] == 3


def test_history_revert_refuses_an_edited_field_without_force(
    ctx: AppContext, animal
) -> None:
    _set_legs(ctx, animal, 3)
    listing = runner.invoke(app, ["history", "record", str(animal.id)[:8]])
    entry = _entry_for(listing.output, "update")
    _set_legs(ctx, animal, 9)

    refused = runner.invoke(app, ["history", "revert", entry, "--yes"])
    assert refused.exit_code == 1
    assert "edited since" in refused.output.lower()
    assert ctx.record_svc.get(str(animal.id)).data["legs"] == 9

    forced = runner.invoke(app, ["history", "revert", entry, "--yes", "--force"])
    assert forced.exit_code == 0, forced.output
    assert ctx.record_svc.get(str(animal.id)).data["legs"] == 4


def test_history_revert_of_a_delete_restores_the_record(
    ctx: AppContext, animal
) -> None:
    ctx.record_svc.delete(str(animal.id))
    ctx.commit()
    entry = str(ctx.history_svc.page(entity_id=animal.id, action="delete")[0].id)[:8]

    result = runner.invoke(app, ["history", "revert", entry, "--yes"])
    assert result.exit_code == 0, result.output
    assert ctx.record_svc.get(str(animal.id)).data["legs"] == 4


def test_history_unknown_entry_fails_cleanly(ctx: AppContext) -> None:
    result = runner.invoke(app, ["history", "show", "deadbeef"])
    assert result.exit_code == 1
    assert "not found" in result.output
