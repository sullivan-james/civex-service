"""Spawns examples/echo_plugin.py as a real subprocess and drives it over
real stdin/stdout pipes -- the strongest available verification of the
wire protocol + fd-dup stdout isolation without a Tier-1 host executor to
drive it for real.
"""

import json
import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).parents[1] / "examples" / "echo_plugin.py"


def _send(proc: subprocess.Popen, frame: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(frame) + "\n")
    proc.stdin.flush()


def _recv(proc: subprocess.Popen) -> dict:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line, "subprocess closed stdout unexpectedly"
    return json.loads(line)


def test_describe_and_run_over_real_stdio_pipes():
    proc = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send(proc, {"type": "describe"})
        describe = _recv(proc)
        assert describe["type"] == "describe_result"
        assert describe["id"] == "example.echo"
        assert describe["capabilities"] == ["commit"]
        assert describe["config_schema"]["required"] == ["text"]

        _send(
            proc,
            {"type": "run", "inputs": {}, "config": {"text": "hello"}},
        )
        result = _recv(proc)
        assert result == {"type": "result", "outputs": {"echo": "hello", "inputs": {}}}

        # A run that triggers a real nested rpc_call (commit) -- we act as
        # the host and answer it before the plugin can produce its result.
        _send(
            proc,
            {"type": "run", "inputs": {"call_commit": True}, "config": {"text": "hi"}},
        )
        call = _recv(proc)
        assert call["type"] == "rpc_call"
        assert call["method"] == "commit"
        _send(
            proc,
            {"type": "rpc_result", "call_id": call["call_id"], "result": {}},
        )
        result = _recv(proc)
        assert result == {
            "type": "result",
            "outputs": {"echo": "hi", "inputs": {"call_commit": True}},
        }
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=10)

    assert proc.returncode == 0, proc.stderr.read() if proc.stderr else None


def test_invalid_config_over_real_stdio_pipes():
    proc = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send(proc, {"type": "run", "inputs": {}, "config": {}})
        err = _recv(proc)
        assert err["type"] == "error"
        assert err["error"]["kind"] == "config_validation_error"
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=10)
