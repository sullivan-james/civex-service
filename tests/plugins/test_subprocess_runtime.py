"""Host side of the Tier 1 (uv-managed subprocess) plugin runtime
(CIVEX-127/137/138/139). Command construction, capability enforcement, and
frame-driving are tested against a plain `sys.executable` child speaking the
civex-plugin-sdk wire protocol directly -- bypassing `uv run`'s dependency
resolution for speed, since civex_plugin_sdk is already importable in this
venv via the uv workspace. The one real `uv run --no-project` end-to-end
path is covered separately in test_subprocess_runtime_uv_e2e.py.
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from civex.domain.dtos import DatasetDTO, FileRef, RecordDTO, SchemaDTO
from civex.domain.exceptions import (
    CapabilityDeniedError,
    PluginExecutionError,
    PluginTimeoutError,
)
from civex.plugins import runtime
from civex.plugins import subprocess_runtime as rt
from civex.plugins.launchers import CommandLauncher

# Arbitrary: the tests only care that whatever version is installed is pinned.
_SDK_VERSION = "9.8.7"

# -- command construction ------------------------------------------------


def test_build_command_without_local_sdk_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real install: no --find-links; the SDK comes from the index, pinned
    to the version this host itself runs."""
    monkeypatch.setattr(rt, "_sdk_find_links_dir", lambda: None)
    monkeypatch.setattr(rt, "_installed_sdk_version", lambda: _SDK_VERSION)
    argv = rt._build_command("uv", Path("/plugins/thing.py"))
    assert argv == [
        "uv",
        "run",
        "--no-project",
        "--with",
        f"civex-plugin-sdk=={_SDK_VERSION}",
        str(Path("/plugins/thing.py")),
    ]


def test_build_command_omits_pin_when_sdk_version_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rt, "_sdk_find_links_dir", lambda: None)
    monkeypatch.setattr(rt, "_installed_sdk_version", lambda: None)
    argv = rt._build_command("uv", Path("/plugins/thing.py"))
    assert argv == ["uv", "run", "--no-project", str(Path("/plugins/thing.py"))]


def test_build_command_with_local_sdk_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "_sdk_find_links_dir", lambda: Path("/wheels"))
    argv = rt._build_command("uv", Path("/plugins/thing.py"))
    assert argv == [
        "uv",
        "run",
        "--no-project",
        "--find-links",
        str(Path("/wheels")),
        str(Path("/plugins/thing.py")),
    ]


def test_find_uv_binary_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVEX_UV_BIN", "/opt/uv/uv")
    assert rt.find_uv_binary() == "/opt/uv/uv"


def test_find_uv_binary_falls_back_to_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVEX_UV_BIN", raising=False)
    monkeypatch.setattr(rt.shutil, "which", lambda name: "/usr/bin/uv")
    assert rt.find_uv_binary() == "/usr/bin/uv"


def test_find_uv_binary_raises_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVEX_UV_BIN", raising=False)
    monkeypatch.setattr(rt.shutil, "which", lambda name: None)
    with pytest.raises(Exception, match="No 'uv' binary found"):
        rt.find_uv_binary()


# -- capability-enforced RPC dispatch --------------------------------------


def _dto_now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeWorkflowContext:
    """Stands in for civex.plugins.base.WorkflowContext -- same method
    surface, canned DTO responses, so dispatcher tests don't need a real
    AppContext/DB."""

    def __init__(self) -> None:
        self.committed = False
        self.updated: list[tuple[str, dict]] = []

    def get_context_record(self) -> RecordDTO:
        return RecordDTO(
            id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            schema_id=uuid.uuid4(),
            schema_name="Subject",
            parent_record_id=None,
            data={"name": "S01"},
            created_at=_dto_now(),
            updated_at=_dto_now(),
        )

    def get_context_dataset(self) -> DatasetDTO:
        return DatasetDTO(
            id=uuid.uuid4(),
            name="study",
            description=None,
            record_count=1,
            created_at=_dto_now(),
        )

    def get_file(self, sha256: str) -> bytes:
        return b"file-bytes"

    def store_file(self, data: bytes, filename: str) -> FileRef:
        return FileRef(sha256="abc123", filename=filename, size=len(data))

    def update_record(self, record_id: str, data: dict) -> RecordDTO:
        self.updated.append((record_id, data))
        return RecordDTO(
            id=uuid.UUID(record_id) if _is_uuid(record_id) else uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            schema_id=uuid.uuid4(),
            schema_name="Subject",
            parent_record_id=None,
            data=data,
            created_at=_dto_now(),
            updated_at=_dto_now(),
        )

    def create_record(
        self, dataset_name, schema_name, data, context_record_id=None
    ) -> RecordDTO:
        return RecordDTO(
            id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            schema_id=uuid.uuid4(),
            schema_name=schema_name,
            parent_record_id=None,
            data=data,
            created_at=_dto_now(),
            updated_at=_dto_now(),
        )

    def get_record(self, record_id: str) -> RecordDTO:
        return self.update_record(record_id, {})

    def find_records(self, dataset_name, **kwargs) -> list[RecordDTO]:
        return [self.get_record(str(uuid.uuid4()))]

    def delete_record(self, record_id: str) -> None:
        pass

    def get_schema(self, name: str) -> SchemaDTO:
        return SchemaDTO(
            id=uuid.uuid4(),
            name=name,
            description=None,
            parent_id=None,
            created_at=_dto_now(),
        )

    def list_schemas(self) -> list[SchemaDTO]:
        return [self.get_schema("Subject")]

    def get_collection(self, name: str) -> DatasetDTO:
        return self.get_context_dataset()

    def list_collections(self) -> list[DatasetDTO]:
        return [self.get_context_dataset()]

    def commit(self) -> None:
        self.committed = True


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


def test_dispatch_denies_undeclared_capability() -> None:
    dispatcher = runtime._HostRpcDispatcher(_FakeWorkflowContext(), [], Path("/tmp"))
    with pytest.raises(CapabilityDeniedError, match="add 'write_records'"):
        dispatcher.dispatch("update_record", {"record_id": "r", "data": {}})


def test_commit_is_answered_and_does_nothing() -> None:
    """Plugins written before a run's writes were kept whole still call it."""
    ctx = _FakeWorkflowContext()
    dispatcher = runtime._HostRpcDispatcher(ctx, [], Path("/tmp"))
    assert dispatcher.dispatch("commit", {}) == {}
    assert ctx.committed is False


def test_an_action_grants_every_function_needing_it() -> None:
    ctx = _FakeWorkflowContext()
    dispatcher = runtime._HostRpcDispatcher(ctx, ["read"], Path("/tmp"))
    for tool in ("get_context_record", "find_records", "list_schemas"):
        dispatcher.dispatch(
            "call_tool", {"tool": tool, "args": {"dataset_name": "study"}}
        )
    with pytest.raises(CapabilityDeniedError):
        dispatcher.dispatch("call_tool", {"tool": "delete_record", "args": {}})


def test_dispatch_update_record_returns_dto_dict() -> None:
    ctx = _FakeWorkflowContext()
    dispatcher = runtime._HostRpcDispatcher(ctx, ["update_record"], Path("/tmp"))
    result = dispatcher.dispatch(
        "update_record", {"record_id": str(uuid.uuid4()), "data": {"x": 1}}
    )
    assert result["data"] == {"x": 1}
    assert ctx.updated


def test_dispatch_call_tool_checks_tool_name_not_the_call_tool_literal() -> None:
    ctx = _FakeWorkflowContext()
    dispatcher = runtime._HostRpcDispatcher(ctx, ["find_records"], Path("/tmp"))
    # declared for find_records...
    result = dispatcher.dispatch(
        "call_tool", {"tool": "find_records", "args": {"dataset_name": "study"}}
    )
    assert "records" in result
    # ...but not for get_schema
    with pytest.raises(CapabilityDeniedError):
        dispatcher.dispatch(
            "call_tool", {"tool": "get_schema", "args": {"name": "Subject"}}
        )


def test_dispatch_call_tool_missing_tool_name_raises() -> None:
    dispatcher = runtime._HostRpcDispatcher(
        _FakeWorkflowContext(), ["find_records"], Path("/tmp")
    )
    with pytest.raises(PluginExecutionError):
        dispatcher.dispatch("call_tool", {"args": {}})


def test_dispatch_unknown_tool_raises() -> None:
    dispatcher = runtime._HostRpcDispatcher(
        _FakeWorkflowContext(), ["not_a_real_tool"], Path("/tmp")
    )
    with pytest.raises(PluginExecutionError):
        dispatcher.dispatch("call_tool", {"tool": "not_a_real_tool", "args": {}})


def test_dispatch_get_file_encodes_binary(tmp_path: Path) -> None:
    dispatcher = runtime._HostRpcDispatcher(
        _FakeWorkflowContext(), ["get_file"], tmp_path
    )
    result = dispatcher.dispatch("get_file", {"sha256": "deadbeef"})
    assert result["encoding"] == "base64"


# -- real subprocess frame-driving (plain python, no uv) --------------------

_TEST_PLUGIN_SOURCE = """\
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin, serve

class TestPlugin(Plugin):
    id = "test.plugin"
    name = "Test"
    capabilities = ["update_record"]

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        if inputs.get("call_host"):
            ctx.update_record("r1", {"x": 1})
        if inputs.get("call_denied"):
            ctx.get_file("deadbeef")  # not declared -> capability_denied
        return {"saw": inputs.get("value")}

if __name__ == "__main__":
    serve(TestPlugin)
"""

_HANG_PLUGIN_SOURCE = """\
import time
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin, serve

class HangPlugin(Plugin):
    id = "test.hang"
    name = "Hang"
    capabilities = []

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        time.sleep(30)
        return {}

if __name__ == "__main__":
    serve(HangPlugin)
"""


def _spawn_plain(script_path: Path, cwd: Path) -> subprocess.Popen:
    return rt._spawn([sys.executable, str(script_path)], cwd)


def _connect(script_path: Path):
    """A connection to the script run with this venv's Python (no uv)."""
    return CommandLauncher([sys.executable, str(script_path)]).start("run")


def test_drive_describe_returns_metadata(tmp_path: Path) -> None:
    script = tmp_path / "plugin.py"
    script.write_text(_TEST_PLUGIN_SOURCE)
    conn = _connect(script)
    try:
        result = runtime.drive_describe(conn)
        assert result.id == "test.plugin"
        assert result.capabilities == ["update_record"]
    finally:
        conn.close()


def test_drive_run_dispatches_declared_rpc_call(tmp_path: Path) -> None:
    script = tmp_path / "plugin.py"
    script.write_text(_TEST_PLUGIN_SOURCE)
    conn = _connect(script)
    ctx = _FakeWorkflowContext()
    dispatcher = runtime._HostRpcDispatcher(ctx, ["update_record"], tmp_path)
    try:
        outputs = runtime.drive_run(
            conn, {"call_host": True, "value": "x"}, {}, dispatcher
        )
        assert outputs == {"saw": "x"}
        assert ctx.updated == [("r1", {"x": 1})]
    finally:
        conn.close()


def test_drive_run_undeclared_capability_fails_the_run(tmp_path: Path) -> None:
    script = tmp_path / "plugin.py"
    script.write_text(_TEST_PLUGIN_SOURCE)
    conn = _connect(script)
    ctx = _FakeWorkflowContext()
    # capabilities passed to the dispatcher deliberately omit get_file, even
    # though the plugin's own declared capabilities list (used only for
    # discovery/display) doesn't include it either -- this is exactly what
    # enforcement is supposed to catch.
    dispatcher = runtime._HostRpcDispatcher(ctx, ["update_record"], tmp_path)
    try:
        with pytest.raises(PluginExecutionError) as excinfo:
            runtime.drive_run(conn, {"call_denied": True}, {}, dispatcher)
    finally:
        conn.close()
    # The classification is a field now, not a prefix glued onto the message
    # (CIVEX-143) -- and it survives the full round trip: host denies the
    # rpc_call, the plugin's Ctx raises RpcError carrying the host's kind
    # rather than flattening it to "rpc_error", and serve() sends it back as
    # the run's top-level error frame.
    assert excinfo.value.kind == "capability_denied"
    assert excinfo.value.retryable is False
    assert "get_file" in str(excinfo.value)


def test_run_with_timeout_kills_process_group_and_raises(tmp_path: Path) -> None:
    script = tmp_path / "hang.py"
    script.write_text(_HANG_PLUGIN_SOURCE)
    conn = _connect(script)
    ctx = _FakeWorkflowContext()
    dispatcher = runtime._HostRpcDispatcher(ctx, [], tmp_path)
    try:
        start = time.monotonic()
        with pytest.raises(PluginTimeoutError):
            runtime.run_with_timeout(
                conn,
                lambda: runtime.drive_run(conn, {}, {}, dispatcher),
                1.0,
                label="hang",
            )
        elapsed = time.monotonic() - start
        assert elapsed < 10.0  # killed promptly, not left to run its full 30s sleep
        time.sleep(0.2)
        assert not conn.alive()  # process actually died
    finally:
        conn.close()


def test_kill_process_group_terminates_child(tmp_path: Path) -> None:
    script = tmp_path / "hang.py"
    script.write_text(_HANG_PLUGIN_SOURCE)
    proc = _spawn_plain(script, tmp_path)
    rt._kill_process_group(proc, grace_seconds=1.0)
    assert proc.poll() is not None


# -- dispatcher against a real WorkflowContext / AppContext ------------------


def test_dispatcher_against_real_workflow_context(
    ctx, make_collection, make_schema, make_record
) -> None:
    from civex.plugins.base import WorkflowContext

    dataset = make_collection("study")
    make_schema("subject", fields=[("name", "string")])
    record = make_record("study", "subject", {"name": "S01"})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)

    dispatcher = runtime._HostRpcDispatcher(
        wf_ctx, ["update_record", "get_context_record"], Path("/tmp")
    )
    seen = dispatcher.dispatch("call_tool", {"tool": "get_context_record", "args": {}})
    assert seen["record"]["data"] == {"name": "S01"}

    updated = dispatcher.dispatch(
        "update_record", {"record_id": str(record.id), "data": {"name": "S02"}}
    )
    assert updated["data"] == {"name": "S02"}


# -- wire protocol version handshake ----------------------------------------


def _described(protocol_version: int):
    from civex_plugin_sdk.protocol import DescribeResult

    return DescribeResult(id="p.x", name="X", protocol_version=protocol_version)


def test_protocol_version_match_passes() -> None:
    from civex_plugin_sdk.protocol import PROTOCOL_VERSION

    described = _described(PROTOCOL_VERSION)
    assert runtime.check_protocol_version(described) is described


def test_newer_plugin_protocol_tells_user_to_update_civex() -> None:
    from civex_plugin_sdk.protocol import PROTOCOL_VERSION

    with pytest.raises(PluginExecutionError, match="civex update") as exc:
        runtime.check_protocol_version(_described(PROTOCOL_VERSION + 1))
    assert exc.value.kind == "protocol_mismatch"


def test_a_plugin_on_an_older_protocol_this_host_still_speaks_runs() -> None:
    """Protocol 2 only added what a plugin may send, so a plugin on 1 runs."""
    described = _described(1)
    assert runtime.check_protocol_version(described) is described


def test_older_plugin_protocol_tells_author_to_upgrade_sdk() -> None:
    with pytest.raises(PluginExecutionError, match="upgrade the plugin's"):
        runtime.check_protocol_version(_described(0))
