"""What a host's permissions allow of an import: the same checks as saving
records and changing the structure by hand, and a file is no more reachable
here than its records are."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.config import FileConfigStore, load_config_at
from civex.context import build_local_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.project import Project, scaffold_project
from civex.server.app import create_app

CSV = b"ID,Name\n1,Ann\n2,Bob\n"


@pytest.fixture()
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "hosted"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("person")
    owner.schema_svc.add_field("person", "id", "string")
    owner.dataset_svc.create("a")
    owner.dataset_svc.create("b")
    owner.dataset_svc.create("vault")
    owner.commit()
    owner.close()
    return root


def _client(root: Path, perms: Permissions) -> TestClient:
    def project(request):
        return Project(
            config=load_config_at(root),
            config_store=FileConfigStore(root),
            actor="Dr Example",
            permissions=perms,
        )

    app = create_app()
    app.state.project_resolver = project
    return TestClient(app, raise_server_exceptions=False)


def _upload(client: TestClient) -> str:
    r = client.put("/api/files/stream?filename=p.csv", content=CSV)
    assert r.status_code == 201, r.text
    return r.json()["sha256"]


def _run(client: TestClient, sha: str, collection: str = "a", **extra):
    body = {
        "sha256": sha,
        "filename": "p.csv",
        "collection": collection,
        "kind": "person",
        "columns": [{"heading": "ID", "field": "id"}],
        **extra,
    }
    return client.post("/api/import/run", json=body)


def test_a_writer_limited_to_one_collection_cannot_import_into_another(root, tmp_path):
    ids = {
        d.name: d.id
        for d in build_local_context(load_config_at(root)).dataset_svc.list_all()
    }
    only_a = Permissions.of(
        p.READ, p.ADD_FILES, p.WRITE_RECORDS, collections=[ids["a"]]
    )
    client = _client(root, only_a)
    sha = _upload(client)
    assert _run(client, sha, "a").status_code == 200
    refused = _run(client, sha, "b")
    assert refused.status_code in (403, 404), refused.text
    assert _run(client, sha, "b", check=True).status_code in (403, 404)


@pytest.mark.parametrize(
    "extra",
    [
        {"kind": "brand_new", "kind_label": "Brand new"},
        {
            "columns": [
                {"heading": "ID", "field": "id"},
                {"heading": "Name", "field": "name", "create": True},
            ]
        },
        {"collection": "fresh", "new_collection": True},
    ],
    ids=["new kind", "new field", "new collection"],
)
def test_a_writer_without_change_structure_cannot_make_structure(root, extra):
    writer = Permissions.of(p.READ, p.ADD_FILES, p.WRITE_RECORDS)
    client = _client(root, writer)
    sha = _upload(client)
    assert _run(client, sha, **extra).status_code == 403
    assert _run(client, sha, check=True, **extra).status_code == 403
    assert _run(client, sha).status_code == 200  # what it may do still works


def test_a_file_only_a_hidden_collection_uses_is_not_there_to_inspect(root):
    owner = build_local_context(load_config_at(root))
    blob = owner.file_svc.store_bytes(CSV, "secret.csv")
    ref = blob.to_dict()
    owner.schema_svc.add_field("person", "scan", "file")
    owner.record_svc.add("vault", "person", {"id": "x", "scan": ref})
    owner.commit()
    ids = {d.name: d.id for d in owner.dataset_svc.list_all()}
    owner.close()
    sees_a = Permissions.of(
        p.READ, p.WRITE_RECORDS, read_collections=[ids["a"]], collections=[ids["a"]]
    )
    params = {"sha256": ref["sha256"], "filename": "secret.csv"}
    assert (
        _client(root, sees_a).get("/api/import/inspect", params=params).status_code
        == 404
    )
    assert (
        _client(root, Permissions.everything())
        .get("/api/import/inspect", params=params)
        .status_code
        == 200
    )
