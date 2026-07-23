"""WorkflowService: single source of truth for workflow YAML file I/O,
extracted from server/routers/workflows.py (CIVEX-54). No prior test coverage
existed for the router this replaces -- these tests cover the behavior for
the first time, not just characterize it.
"""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError

_VALID_YAML = """\
name: parse-audio-dates
description: A workflow
steps:
  - id: step-one
    plugin: civex.get_field
    config:
      field: subject
"""


def test_list_defs_empty_when_no_workflows_dir_populated(ctx: AppContext) -> None:
    assert ctx.workflow_svc.list_defs() == []


def test_save_then_list_defs_returns_it(ctx: AppContext) -> None:
    ctx.workflow_svc.save("parse-audio-dates", _VALID_YAML)
    defs = ctx.workflow_svc.list_defs()
    assert len(defs) == 1
    path, wf = defs[0]
    assert path.stem == "parse-audio-dates"
    assert wf.name == "parse-audio-dates"


def test_list_defs_skips_unparseable_files(ctx: AppContext) -> None:
    wf_dir = ctx.workflow_svc._dir
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "broken.yaml").write_text("not: [valid, workflow", encoding="utf-8")
    assert ctx.workflow_svc.list_defs() == []


def test_find_by_name_matches_declared_name_or_filename_stem(ctx: AppContext) -> None:
    ctx.workflow_svc.save("some-stem", _VALID_YAML)
    assert ctx.workflow_svc.find_by_name("parse-audio-dates") is not None
    assert ctx.workflow_svc.find_by_name("some-stem") is not None
    assert ctx.workflow_svc.find_by_name("ghost") is None


def test_get_returns_path_def_and_raw_content(ctx: AppContext) -> None:
    ctx.workflow_svc.save("parse-audio-dates", _VALID_YAML)
    path, wf, content = ctx.workflow_svc.get("parse-audio-dates")
    assert path.name == "parse-audio-dates.yaml"
    assert wf.name == "parse-audio-dates"
    assert content == _VALID_YAML


def test_get_unknown_stem_raises_not_found(ctx: AppContext) -> None:
    with pytest.raises(NotFoundError, match="ghost"):
        ctx.workflow_svc.get("ghost")


def test_get_invalid_yaml_raises_validation_error(ctx: AppContext) -> None:
    wf_dir = ctx.workflow_svc._dir
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "broken.yaml").write_text("not: [valid, workflow", encoding="utf-8")
    with pytest.raises(ValidationError, match="Invalid workflow YAML"):
        ctx.workflow_svc.get("broken")


def test_list_raw_returns_full_source_text(ctx: AppContext) -> None:
    ctx.workflow_svc.save("parse-audio-dates", _VALID_YAML)
    raw = ctx.workflow_svc.list_raw()
    assert raw == [{"filename": "parse-audio-dates.yaml", "content": _VALID_YAML}]


def test_validate_rejects_bad_stem(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="stem must contain only"):
        ctx.workflow_svc.validate("bad stem!", _VALID_YAML)


def test_validate_rejects_invalid_yaml(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="Invalid workflow YAML"):
        ctx.workflow_svc.validate("ok-stem", "not: [valid")


def test_validate_does_not_write_anything(ctx: AppContext) -> None:
    ctx.workflow_svc.validate("parse-audio-dates", _VALID_YAML)
    assert ctx.workflow_svc.list_defs() == []


def test_save_rejects_bad_stem_without_writing(ctx: AppContext) -> None:
    with pytest.raises(ValidationError):
        ctx.workflow_svc.save("bad stem!", _VALID_YAML)
    assert ctx.workflow_svc.list_defs() == []


_CYCLE_YAML = """\
name: cyclic
steps:
  - id: a
    plugin: civex.load_csv
    inputs:
      bytes: b.table
  - id: b
    plugin: civex.load_csv
    inputs:
      bytes: a.table
"""


def test_validate_rejects_dependency_cycle(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        ctx.workflow_svc.validate("cyclic", _CYCLE_YAML)


def test_save_rejects_dependency_cycle_without_writing(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        ctx.workflow_svc.save("cyclic", _CYCLE_YAML)
    assert ctx.workflow_svc.list_defs() == []


def test_delete_removes_the_file(ctx: AppContext) -> None:
    ctx.workflow_svc.save("parse-audio-dates", _VALID_YAML)
    ctx.workflow_svc.delete("parse-audio-dates")
    assert ctx.workflow_svc.list_defs() == []


def test_delete_unknown_stem_raises_not_found(ctx: AppContext) -> None:
    with pytest.raises(NotFoundError, match="ghost"):
        ctx.workflow_svc.delete("ghost")


def test_delete_blocked_by_pending_job(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    ctx.workflow_svc.save("parse-audio-dates", _VALID_YAML)
    make_collection("study")
    make_schema("doc", fields=[("subject", "string")])
    record = make_record("study", "doc", {"subject": "x"})
    ctx.job_svc.enqueue_manual("parse-audio-dates", record)
    ctx.commit()

    with pytest.raises(ValidationError, match="pending/running job"):
        ctx.workflow_svc.delete("parse-audio-dates")
    assert ctx.workflow_svc.list_defs() != []


def test_delete_force_ignores_pending_job(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    ctx.workflow_svc.save("parse-audio-dates", _VALID_YAML)
    make_collection("study")
    make_schema("doc", fields=[("subject", "string")])
    record = make_record("study", "doc", {"subject": "x"})
    ctx.job_svc.enqueue_manual("parse-audio-dates", record)
    ctx.commit()

    ctx.workflow_svc.delete("parse-audio-dates", force=True)
    assert ctx.workflow_svc.list_defs() == []


def test_delete_not_blocked_by_completed_job(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    ctx.workflow_svc.save("parse-audio-dates", _VALID_YAML)
    make_collection("study")
    make_schema("doc", fields=[("subject", "string")])
    record = make_record("study", "doc", {"subject": "x"})
    job = ctx.job_svc.enqueue_manual("parse-audio-dates", record)
    ctx.job_svc.mark_completed(job.id)
    ctx.commit()

    ctx.workflow_svc.delete("parse-audio-dates")
    assert ctx.workflow_svc.list_defs() == []
