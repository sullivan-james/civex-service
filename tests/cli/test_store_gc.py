from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.config import load_config
from civex.context import build_local_context
from civex.main import app

runner = CliRunner()


def test_store_gc_dry_run_then_apply(project_dir: Path) -> None:
    ctx = build_local_context(load_config())
    ref = ctx.file_svc._store.put(b"orphan", "orphan.txt")
    ctx.commit()
    ctx.close()

    result = runner.invoke(app, ["store", "gc", "--grace-days", "0"])
    assert result.exit_code == 0
    assert "Collectible 1 object(s)" in result.output
    assert "Dry run" in result.output

    ctx2 = build_local_context(load_config())
    assert ctx2.file_svc._store.exists(ref.sha256)
    ctx2.close()

    result = runner.invoke(app, ["store", "gc", "--grace-days", "0", "--apply"])
    assert result.exit_code == 0
    assert "Deleted 1 object(s)" in result.output

    ctx3 = build_local_context(load_config())
    assert not ctx3.file_svc._store.exists(ref.sha256)
    ctx3.close()
