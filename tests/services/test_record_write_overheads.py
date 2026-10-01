"""Per-record write costs that must not creep back: a prefix lookup is an index
range (not a scan), workflow files are parsed when they change (not per
record), and an insert that cites no file doesn't read file_references."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event

from civex.context import AppContext


@contextmanager
def statements(ctx: AppContext):
    seen: list[str] = []

    def record(conn, cursor, statement, *_):
        seen.append(statement)

    engine = ctx._session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_short_id_prefix_finds_the_record_without_casting_the_id(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_collection("study")
    rec = make_record("study", "patient", {})
    ctx.commit()

    with statements(ctx) as seen:
        found = ctx.record_svc._records.get_by_prefix(str(rec.id)[:8])
        dashed = ctx.record_svc._records.get_by_prefix(str(rec.id)[:13])

    assert found is not None and found.id == rec.id
    assert dashed is not None and dashed.id == rec.id
    assert not any("CAST" in s.upper() and "LIKE" in s.upper() for s in seen)


def test_prefix_that_cannot_match_returns_nothing(ctx: AppContext):
    repo = ctx.record_svc._records
    assert repo.get_by_prefix("not-hex!") is None
    assert repo.get_by_prefix("f" * 40) is None


def test_inserting_a_record_with_no_files_never_reads_file_references(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("patient", fields=[("name", "string")])
    make_collection("study")

    with statements(ctx) as seen:
        ctx.record_svc.add("study", "patient", {"name": "x"})

    assert not any("file_references" in s for s in seen)


def test_workflow_files_are_parsed_once_until_they_change(
    ctx: AppContext, project_dir, monkeypatch
):
    import civex.services.workflow_job_service as mod

    wf_dir = project_dir / "_civex" / "workflows"
    wf_dir.mkdir(exist_ok=True)
    path = wf_dir / "w.yaml"
    path.write_text(
        "name: w\ntriggers:\n  record_created:\n    schema: patient\nsteps: []\n"
    )
    calls = []
    real = mod.load_workflow
    monkeypatch.setattr(
        mod, "load_workflow", lambda p: calls.append(p) or real(p)
    )
    svc = ctx.job_svc

    for _ in range(5):
        svc._load_workflows()
    assert len(calls) == 1

    path.write_text(path.read_text() + "\n# edited\n")
    svc._load_workflows()
    assert len(calls) == 2
