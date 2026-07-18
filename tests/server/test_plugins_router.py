"""HTTP-level tests for /api/plugins, backed by PluginService (CIVEX-54). No
prior test coverage existed for this router -- new coverage, not just
characterization.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

_VALID_CODE = """\
from civex.plugins.base import BasePlugin, WorkflowContext

class Plugin(BasePlugin):
    id = "project.my_plugin"
    name = "My Plugin"

    def run(self, inputs, config, ctx: WorkflowContext) -> dict:
        return {}
"""


def test_list_plugins_includes_builtins(client: TestClient) -> None:
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert any(pid.startswith("civex.") for pid in ids)


def test_save_plugin_json_then_list(client: TestClient) -> None:
    save_resp = client.post(
        "/api/plugins", json={"name": "my_plugin", "code": _VALID_CODE}
    )
    assert save_resp.status_code == 201
    assert save_resp.json() == {"filename": "my_plugin.py"}

    list_resp = client.get("/api/plugins")
    assert any(p["id"] == "project.my_plugin" for p in list_resp.json())


def test_save_plugin_json_rejects_bad_name(client: TestClient) -> None:
    resp = client.post("/api/plugins", json={"name": "BadName", "code": _VALID_CODE})
    assert resp.status_code == 422


def test_save_plugin_json_rejects_missing_plugin_class(client: TestClient) -> None:
    resp = client.post("/api/plugins", json={"name": "my_plugin", "code": "x = 1"})
    assert resp.status_code == 422


def test_upload_plugin(client: TestClient) -> None:
    resp = client.post(
        "/api/plugins/upload",
        files={"file": ("my_plugin.py", _VALID_CODE, "text/x-python")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"filename": "my_plugin.py", "plugin_id": "project.my_plugin"}


def test_upload_plugin_rejects_non_py_file(client: TestClient) -> None:
    resp = client.post(
        "/api/plugins/upload",
        files={"file": ("notes.txt", "hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_plugin_rejects_path_traversal(client: TestClient) -> None:
    resp = client.post(
        "/api/plugins/upload",
        files={"file": ("../escape.py", _VALID_CODE, "text/x-python")},
    )
    assert resp.status_code == 400
