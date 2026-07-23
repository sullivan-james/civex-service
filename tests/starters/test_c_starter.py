"""Compiles and exercises the C/C++ Tier 2 plugin starter (starters/c/)
against real stdin/stdout, the same way a `docker run -i <image> <mode>`
invocation would talk to it. Skipped if no C compiler is on PATH (mirrors
tests/plugins/test_subprocess_runtime_uv_e2e.py's skipif-on-missing-tool
pattern for `uv`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STARTER_DIR = Path(__file__).resolve().parents[2] / "starters" / "c"

_CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
pytestmark = pytest.mark.skipif(_CC is None, reason="no C compiler is on PATH")


@pytest.fixture(scope="module")
def plugin_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("c_starter_build")
    binary = out_dir / "plugin"
    src = STARTER_DIR / "src"
    subprocess.run(
        [
            _CC,
            "-O0",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-std=c11",
            "-o",
            str(binary),
            str(src / "json.c"),
            str(src / "shim.c"),
            str(src / "plugin.c"),
            "-lm",
        ],
        check=True,
    )
    return binary


def _run(binary: Path, mode: str, stdin_text: str) -> tuple[str, str, int]:
    proc = subprocess.run(
        [str(binary), mode],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.stdout, proc.stderr, proc.returncode


def test_describe_reports_the_plugin_contract(plugin_binary: Path) -> None:
    stdout, _stderr, rc = _run(plugin_binary, "describe", '{"type":"describe"}\n')
    assert rc == 0
    frame = json.loads(stdout.strip())
    assert frame["type"] == "describe_result"
    assert frame["id"] == "my_project.c_example_sum"
    assert frame["capabilities"] == []
    assert [i["name"] for i in frame["inputs"]] == ["a", "b"]
    assert [o["name"] for o in frame["outputs"]] == ["sum"]


def test_run_computes_the_sum(plugin_binary: Path) -> None:
    request = json.dumps({"type": "run", "inputs": {"a": 2, "b": 3.5}, "config": {}})
    stdout, _stderr, rc = _run(plugin_binary, "run", request + "\n")
    assert rc == 0
    frame = json.loads(stdout.strip())
    assert frame == {"type": "result", "outputs": {"sum": 5.5}}


def test_run_with_missing_input_returns_a_structured_error(plugin_binary: Path) -> None:
    request = json.dumps({"type": "run", "inputs": {"a": 2}, "config": {}})
    stdout, _stderr, rc = _run(plugin_binary, "run", request + "\n")
    assert rc == 0
    frame = json.loads(stdout.strip())
    assert frame["type"] == "error"
    assert frame["call_id"] is None
    assert frame["error"]["kind"] == "validation_error"
    assert frame["error"]["retryable"] is False


def test_malformed_json_on_stdin_returns_a_protocol_error(plugin_binary: Path) -> None:
    # Genuinely unparseable input is a harder failure than a well-formed
    # frame of the wrong type -- shim_serve exits nonzero here (see
    # src/shim.c) even though it still writes a structured error frame.
    stdout, _stderr, rc = _run(plugin_binary, "run", "not json\n")
    assert rc == 1
    frame = json.loads(stdout.strip())
    assert frame["type"] == "error"
    assert frame["error"]["kind"] == "protocol_error"


def test_wrong_frame_type_for_the_mode_returns_a_protocol_error(plugin_binary: Path) -> None:
    stdout, _stderr, rc = _run(plugin_binary, "describe", '{"type":"run","inputs":{}}\n')
    assert rc == 0
    frame = json.loads(stdout.strip())
    assert frame["type"] == "error"
    assert frame["error"]["kind"] == "protocol_error"


def test_stray_stdout_from_plugin_code_never_reaches_the_protocol_stream(
    plugin_binary: Path,
) -> None:
    """The fd-dup isolation trick (isolate_stdout() in shim.c): plugin.c's
    invoke() deliberately printf()s a debug line before returning. Captured
    stdout must contain exactly the one JSON result line -- proves the
    debug print really went to /dev/null, not merely that we didn't look at
    it."""
    request = json.dumps({"type": "run", "inputs": {"a": 10, "b": 20}, "config": {}})
    stdout, stderr, rc = _run(plugin_binary, "run", request + "\n")
    assert rc == 0
    lines = stdout.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"type": "result", "outputs": {"sum": 30}}
    assert stderr == ""
