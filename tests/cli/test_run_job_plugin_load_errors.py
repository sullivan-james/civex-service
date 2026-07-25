"""CIVEX-112: discover_user_plugins() used to run before run_job()/
run_pending_jobs() started capturing logs, so a broken plugin file's
log.warning() -- which file failed and why -- never reached the job's
own log, only the process's own stderr. Discovery now runs inside the
log-capture block, so this is where that surfaces end to end.
"""

from __future__ import annotations

from civex.cli.utils import drain_jobs
from civex.context import AppContext


def test_broken_plugin_file_warning_lands_in_the_job_log(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    dataset = make_collection("study")
    make_schema("doc", fields=[("name", "string")])
    record = make_record("study", "doc", {"name": "x"})

    plugins_dir = ctx.plugin_svc._dir
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "broken_plugin.py").write_text("this is not valid python (((")

    wf_dir = ctx.workflow_svc._dir
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "fine.yaml").write_text("""
name: fine
steps:
  - id: read
    plugin: civex.get_field
    config: {field: name}
""")
    job = ctx.job_svc.enqueue_manual("fine", record)
    ctx.commit()

    drain_jobs(ctx)

    finished = ctx.job_svc.get_job(job.id)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.log is not None
    assert "broken_plugin.py" in finished.log
