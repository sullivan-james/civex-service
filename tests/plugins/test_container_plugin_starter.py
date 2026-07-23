"""Spawns templates/container-plugins/python/plugin.py as a real subprocess
and drives it exactly the way the future Tier 2 (container) host runtime
will: `<script> describe` / `<script> run`, mode via argv rather than a
leading control frame -- the strongest available check that the starter
template's shim call (civex_plugin_sdk.serve_container) actually speaks the
wire protocol end to end (CIVEX-149).

Runs the script directly with sys.executable rather than through Docker
(not assumed to be installed in CI) -- civex_plugin_sdk is already on the
path via this repo's own uv workspace venv, the same shortcut
civex-plugin-sdk's own test_e2e_subprocess.py takes for Tier 1.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parents[2] / "templates" / "container-plugins" / "python"
PLUGIN_SCRIPT = TEMPLATE_DIR / "plugin.py"


def _run_mode(mode: str, stdin_frame: dict | None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(PLUGIN_SCRIPT), mode],
        input=json.dumps(stdin_frame) + "\n" if stdin_frame is not None else "",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_describe_mode_reports_the_starter_plugins_contract():
    result = _run_mode("describe", None)
    assert result["type"] == "describe_result"
    assert result["id"] == "my_project.my_container_plugin"
    assert result["capabilities"] == []


def test_run_mode_executes_invoke_and_returns_a_result():
    result = _run_mode("run", {"type": "run", "inputs": {}, "config": {}})
    assert result == {"type": "result", "outputs": {}}


def test_dockerfile_builds_from_python_and_entrypoints_the_shim():
    dockerfile = (TEMPLATE_DIR / "Dockerfile").read_text()
    assert "FROM python:" in dockerfile
    assert "civex-plugin-sdk" in dockerfile
    assert 'ENTRYPOINT ["python", "plugin.py"]' in dockerfile


def test_manifest_id_matches_the_plugin_source():
    import tomllib

    manifest = tomllib.loads((TEMPLATE_DIR / "civex-plugin.toml").read_text())
    describe = _run_mode("describe", None)
    assert manifest["id"] == describe["id"]
    assert manifest["name"] == describe["name"]
    assert manifest["category"] == describe["category"]
    assert manifest["capabilities"] == describe["capabilities"]
