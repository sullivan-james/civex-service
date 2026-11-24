"""`civex workflow try` prints what a workflow would do and keeps nothing;
`enable`/`disable` switch its triggers."""

from __future__ import annotations

from typer.testing import CliRunner

from civex.context import AppContext
from civex.main import app

runner = CliRunner()

_COPY = """\
name: copy-subject
triggers:
  record_updated:
    schema: doc
steps:
  - id: read
    plugin: civex.value_from_filename@1
    config:
      field: subject
  - id: save
    plugin: civex.set_fields@1
    config:
      field: title
    inputs:
      value: read.value
"""


def test_try_prints_the_change_and_keeps_nothing(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    make_collection("study")
    make_schema("doc", fields=[("subject", "string"), ("title", "string")])
    record = make_record("study", "doc", {"subject": "Whale song", "title": "old"})
    ctx.workflow_svc.save("copy-subject", _COPY)

    result = runner.invoke(
        app, ["workflow", "try", "copy-subject", "--record", str(record.id)[:8]]
    )
    assert result.exit_code == 0, result.output
    assert "Updated" in result.output
    assert "Whale song" in result.output
    assert "Nothing was kept" in result.output
    ctx.rollback()
    assert ctx.record_svc.get(str(record.id)).data["title"] == "old"


def test_disable_then_enable(ctx: AppContext) -> None:
    ctx.workflow_svc.save("copy-subject", _COPY)
    off = runner.invoke(app, ["workflow", "disable", "copy-subject"])
    assert off.exit_code == 0, off.output
    assert ctx.workflow_svc.get("copy-subject")[1].enabled is False
    on = runner.invoke(app, ["workflow", "enable", "copy-subject"])
    assert on.exit_code == 0, on.output
    assert ctx.workflow_svc.get("copy-subject")[1].enabled is True
