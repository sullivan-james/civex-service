"""`GET /bundle/plan`, `GET /bundle` and `POST /bundle/import` (what the app's
Export bundle… and Import bundle… use) say what a bundle holds, write it, and
read it back with everything a schema carries."""

from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from civex.domain import bundle as spec


def _setup(client: TestClient) -> str:
    client.post(
        "/api/schemas",
        json={
            "name": "species",
            "label": "Species",
            "fields": [
                {"name": "common_name", "type": "string", "label": "Common name"}
            ],
        },
    )
    client.post(
        "/api/schemas",
        json={
            "name": "encounter",
            "display_template": "{depth}",
            "fields": [
                {
                    "name": "species",
                    "type": "reference",
                    "required": True,
                    "restrictions": {"schema": "species"},
                },
                {
                    "name": "depth",
                    "type": "float",
                    "restrictions": {"min": 0, "unit": "m"},
                    "default": 1.5,
                },
            ],
        },
    )
    client.post(
        "/api/collections",
        json={"name": "study", "timezone": "Europe/London"},
    )
    seal = client.post(
        "/api/collections/study/records",
        json={"schema_name": "species", "data": {"common_name": "Seal"}},
    ).json()
    client.post(
        "/api/collections/study/records",
        json={"schema_name": "encounter", "data": {"species": seal["id"], "depth": 3}},
    )
    return seal["id"]


def test_plan_and_download_are_the_same_bundle(client: TestClient) -> None:
    _setup(client)
    plan = client.get("/api/bundle/plan").json()
    assert (plan["schemas"], plan["records"], plan["collections"]) == (2, 2, ["study"])
    assert plan["include_files"] is True
    assert client.get("/api/bundle/plan?files=false").json()["include_files"] is False

    resp = client.get("/api/bundle")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "civex-bundle.civex.zip" in resp.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        manifest = json.loads(zf.read(spec.MANIFEST))
        lines = zf.read(spec.RECORDS).decode().splitlines()
    assert manifest["records"] == 2 and len(lines) == 2
    schema = next(s for s in manifest["schemas"] if s["name"] == "species")
    assert schema["label"] == "Species"
    assert schema["fields"][0]["label"] == "Common name"

    structure = client.get("/api/bundle?data=false")
    with zipfile.ZipFile(io.BytesIO(structure.content)) as zf:
        assert spec.RECORDS not in zf.namelist()


def test_import_reads_back_restrictions_defaults_templates_and_ids(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    seal_id = _setup(client)
    bundle = client.get("/api/bundle").content

    # A second, empty project to read it into.
    from typer.testing import CliRunner

    from civex.main import app as cli_app
    from civex.server.app import create_app

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert CliRunner().invoke(cli_app, ["init", "--sqlite", str(other)]).exit_code == 0
    target = TestClient(create_app(), raise_server_exceptions=False)

    response = target.post(
        "/api/bundle/import",
        files={"file": ("study.civex.zip", bundle, "application/zip")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schemas_new"] == 2 and body["records_added"] == 2
    assert body["skipped"] == []

    fields = {
        f["name"]: f for f in target.get("/api/schemas/encounter").json()["fields"]
    }
    assert fields["species"]["restrictions"] == {"schema": "species"}
    assert fields["depth"]["restrictions"] == {"min": 0, "unit": "m"}
    assert fields["depth"]["default"] == 1.5
    assert target.get("/api/schemas/encounter").json()["display_template"] == "{depth}"
    assert target.get("/api/collections/study").json()["timezone"] == "Europe/London"
    assert target.get(f"/api/records/{seal_id}").status_code == 200

    again = target.post(
        "/api/bundle/import",
        files={"file": ("study.civex.zip", bundle, "application/zip")},
    ).json()
    assert again["records_added"] == 0 and again["records_existing"] == 2


def test_something_that_is_not_a_bundle_is_a_400(client: TestClient) -> None:
    response = client.post(
        "/api/bundle/import", files={"file": ("d.yaml", b"schemas: []", "text/yaml")}
    )
    assert response.status_code == 400
    assert "not a civex bundle" in response.json()["detail"]
