"""POST /restore (what the web UI's import uses) must read back everything
`civex dump` writes, the same as `civex restore`: it once created fields from
name, type and required only, so an imported reference field pointed at
nothing and the record form had no records to search."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

DUMP = {
    "schemas": [
        {"name": "species", "fields": [{"name": "common_name", "type": "string"}]},
        {
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
                    "default_value": 1.5,
                },
                {
                    "name": "photo",
                    "type": "file",
                    "restrictions": {"filename_template": "{depth}-{species}{ext}"},
                },
            ],
        },
    ],
    "datasets": [
        {
            "name": "study",
            "scope": "local",
            "timezone": "Europe/London",
            "schemas": ["species", "encounter"],
        }
    ],
}


def test_the_web_restore_keeps_restrictions_defaults_and_templates(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/restore", files={"file": ("d.yaml", yaml.dump(DUMP), "application/yaml")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["schemas"] == 2

    fields = {
        f["name"]: f for f in client.get("/api/schemas/encounter").json()["fields"]
    }
    assert fields["species"]["restrictions"] == {"schema": "species"}
    assert fields["depth"]["restrictions"] == {"min": 0, "unit": "m"}
    assert fields["depth"]["default"] == 1.5
    assert fields["photo"]["restrictions"] == {
        "filename_template": "{depth}-{species}{ext}"
    }
    assert client.get("/api/schemas/encounter").json()["display_template"] == "{depth}"
    assert client.get("/api/collections/study").json()["timezone"] == "Europe/London"


def test_an_old_dump_without_restrictions_still_restores(client: TestClient) -> None:
    old = {"schemas": [{"name": "a", "fields": [{"name": "x", "type": "string"}]}]}
    response = client.post(
        "/api/restore", files={"file": ("d.yaml", yaml.dump(old), "application/yaml")}
    )
    assert response.status_code == 200, response.text
