"""HTTP-level tests for /api/plugins, backed by PluginService (CIVEX-54). No
prior test coverage existed for this router -- new coverage, not just
characterization.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

_VALID_CODE = """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.my_plugin"
    name = "My Plugin"

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        return {}

if __name__ == "__main__":
    serve(Plugin)
"""


def test_list_plugins_includes_builtins(client: TestClient) -> None:
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert any(pid.startswith("civex.") for pid in ids)


def test_list_plugins_returns_the_full_declared_contract(client: TestClient) -> None:
    """PluginInfo mirrors PluginService.list_registered() field-for-field
    (CIVEX-144) -- before this, name/category/capabilities/inputs/outputs
    were silently dropped by pydantic's default extra="ignore", even though
    the service already returned them."""
    resp = client.get("/api/plugins")
    plugins = {p["id"]: p for p in resp.json()}
    get_field = plugins["civex.get_field"]
    assert get_field["name"] == "Get Field"
    assert get_field["category"] == "data-access"
    assert get_field["outputs"] == [
        {
            "name": "value",
            "type": "any",
            "required": True,
            "description": "The field's current value, or null if unset.",
        }
    ]
    assert get_field["config_schema"]["properties"]["field"]["type"] == "string"

    save_field = plugins["civex.save_field"]
    assert save_field["capabilities"] == ["update_record"]


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


def _make_container_plugin(client: TestClient, name: str = "my_plugin") -> None:
    from civex.config import find_project_root

    root = find_project_root() / "_civex" / "plugins" / name
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (root / "civex-plugin.toml").write_text(
        'id = "example.my_plugin"\nname = "My Plugin"\n', encoding="utf-8"
    )
    (root / "src" / "plugin.c").write_text("int main() { return 0; }\n", encoding="utf-8")


def test_list_container_plugins(client: TestClient) -> None:
    _make_container_plugin(client)
    resp = client.get("/api/plugins/containers")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "name": "my_plugin",
            "files": ["Dockerfile", "civex-plugin.toml", "src/plugin.c"],
        }
    ]


def test_get_container_plugin(client: TestClient) -> None:
    _make_container_plugin(client)
    resp = client.get("/api/plugins/containers/my_plugin")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "my_plugin"
    assert body["files"]["Dockerfile"] == "FROM scratch\n"


def test_get_container_plugin_404_for_unknown(client: TestClient) -> None:
    resp = client.get("/api/plugins/containers/nope")
    assert resp.status_code == 404


def test_save_container_plugin_file_triggers_rebuild(client: TestClient) -> None:
    """docker isn't installed in this environment, so this exercises the
    real failure path -- the important thing is the endpoint always returns
    a build result rather than erroring."""
    _make_container_plugin(client)
    resp = client.put(
        "/api/plugins/containers/my_plugin",
        json={"path": "Dockerfile", "content": "FROM alpine\n"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "docker" in body["log"]

    get_resp = client.get("/api/plugins/containers/my_plugin")
    assert get_resp.json()["files"]["Dockerfile"] == "FROM alpine\n"


def test_save_container_plugin_file_404_for_unknown_plugin(client: TestClient) -> None:
    resp = client.put(
        "/api/plugins/containers/nope",
        json={"path": "Dockerfile", "content": "FROM alpine\n"},
    )
    assert resp.status_code == 404


def test_save_container_plugin_file_rejects_path_traversal(client: TestClient) -> None:
    _make_container_plugin(client)
    resp = client.put(
        "/api/plugins/containers/my_plugin",
        json={"path": "../../escape.txt", "content": "x"},
    )
    assert resp.status_code == 400


def test_list_plugins_reports_filename_for_user_plugins_only(
    client: TestClient,
) -> None:
    client.post("/api/plugins", json={"name": "my_plugin", "code": _VALID_CODE})
    plugins = {p["id"]: p for p in client.get("/api/plugins").json()}
    assert plugins["project.my_plugin"]["filename"] == "my_plugin.py"
    builtin = next(p for pid, p in plugins.items() if pid.startswith("civex."))
    assert builtin["filename"] is None


def test_get_plugin_source(client: TestClient) -> None:
    client.post("/api/plugins", json={"name": "my_plugin", "code": _VALID_CODE})
    resp = client.get("/api/plugins/my_plugin.py/source")
    assert resp.status_code == 200
    assert resp.json() == {"filename": "my_plugin.py", "code": _VALID_CODE}


def test_get_plugin_source_missing_file(client: TestClient) -> None:
    resp = client.get("/api/plugins/does_not_exist.py/source")
    assert resp.status_code == 404


def test_get_plugin_source_rejects_non_py_filename(client: TestClient) -> None:
    resp = client.get("/api/plugins/notes.txt/source")
    assert resp.status_code == 400
