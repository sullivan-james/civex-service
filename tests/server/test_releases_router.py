"""HTTP contract for releases."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(releases_client: TestClient) -> TestClient:
    return releases_client


def _study(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "sample"})
    client.post("/api/schemas/sample/fields", json={"name": "site", "type": "string"})
    client.post("/api/schemas/sample/fields", json={"name": "photo", "type": "file"})
    photo = client.put(
        "/api/files/stream?filename=p.jpg",
        content=b"a photo",
        headers={"content-length": "7"},
    )
    assert photo.status_code in (200, 201), photo.text
    for name in ("north", "south"):
        client.post("/api/collections", json={"name": name})
        data = {"site": name, **({"photo": photo.json()} if name == "north" else {})}
        made = client.post(
            f"/api/collections/{name}/records",
            json={"schema_name": "sample", "data": data},
        )
        assert made.status_code == 201, made.text


def test_plan_make_read_cite_verify_and_download(client: TestClient):
    _study(client)
    plan = client.post("/api/releases/plan", json={"collections": ["north"]})
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["records"] == 1 and body["collections"] == {"north": 1}
    assert body["files"] == 1 and body["by_drive"][0]["files"] == 1

    preview = client.post(
        "/api/releases/citation-preview",
        json={"name": "v1", "title": "Survey", "authors": [{"name": "Ada Lovelace"}]},
    )
    assert preview.status_code == 200 and "(Version v1)" in preview.json()["text"]

    made = client.post(
        "/api/releases",
        json={
            "name": "v1",
            "title": "Survey",
            "authors": [{"name": "Ada Lovelace", "orcid": "0000-0002-1825-0097"}],
            "keywords": ["seals"],
            "doi": "10.1234/abc",
            "collections": ["north"],
        },
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["content_hash"].startswith("sha256:")
    assert body["scope"] == {"collections": ["north"]}
    assert body["authors"][0]["orcid"] == "0000-0002-1825-0097"
    assert body["keywords"] == ["seals"] and body["counts"]["files"] == 1
    assert body["file_name"] == "release-v1.civex.zip"

    assert [r["name"] for r in client.get("/api/releases").json()] == ["v1"]
    assert client.get("/api/releases/v1").json()["id"] == body["id"]
    assert (
        client.post("/api/releases", json={"name": "v1", "title": "x"}).status_code
        == 409
    )

    cite = client.get("/api/releases/v1/citation").json()
    assert "(Version v1)" in cite["text"] and cite["bibtex"].startswith("@misc{")
    assert "cff-version: 1.2.0" in cite["cff"] and "orcid" in cite["cff"]

    verified = client.post("/api/releases/v1/verify").json()
    assert verified["matches"] is True and verified["files"] == 1
    deep = client.post("/api/releases/v1/verify?deep=true").json()
    assert deep["matches"] is True and deep["files_read"] == 1

    download = client.get("/api/releases/v1/bundle")
    assert download.status_code == 200 and download.content[:2] == b"PK"
    assert "v1" in download.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(download.content)) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("bundle.json"))
    # The records, the citation, and the files the records cite.
    assert "records.jsonl" in names and "CITATION.cff" in names
    assert manifest["files"]["included"] is True and manifest["files"]["count"] == 1
    (file_member,) = [n for n in names if n.startswith("files/")]
    assert file_member.startswith("files/")


def test_the_files_come_out_as_a_folder_or_a_small_zip(client: TestClient):
    _study(client)
    client.post("/api/releases", json={"name": "v1", "title": "Survey"})
    plan = client.post("/api/releases/v1/files/plan").json()
    assert [i["path"] for i in plan["items"]] == [] or plan["files"] == 1
    assert plan["zip_allowed"] is True

    zipped = client.post("/api/releases/v1/files/zip")
    assert zipped.status_code == 200, zipped.text
    names = zipfile.ZipFile(io.BytesIO(zipped.content)).namelist()
    assert "manifest-sha256.txt" in names and "CITATION.cff" in names
    assert any(n.endswith("p.jpg") for n in names)

    folder = client.post("/api/releases/v1/files/export", json={"mode": "copy"})
    assert folder.status_code == 200, folder.text
    assert folder.json()["copied"] == 1


def test_a_release_is_exported_into_any_folder_in_a_form_read_back_in(
    client: TestClient, tmp_path
):
    """Any folder of this computer, not only a drive set up in Settings; the
    files, and beside them the records as civex reads them back."""
    import pathlib

    _study(client)
    client.post("/api/releases", json={"name": "v1", "title": "Survey"})
    made = client.post(
        "/api/releases/v1/files/export",
        json={"mode": "link", "folder": str(tmp_path)},
    )
    assert made.status_code == 200, made.text
    dest = pathlib.Path(made.json()["dest"])
    assert dest.parent == tmp_path and dest.name == "release-v1"
    names = {p.name for p in dest.iterdir()}
    assert {"manifest-sha256.txt", "CITATION.cff"} <= names
    (copy,) = [n for n in names if n.endswith(".civex.zip")]
    with zipfile.ZipFile(dest / copy) as zf:
        assert "records.jsonl" in zf.namelist()
    # Made again into the same folder, it is refreshed, not refused.
    again = client.post(
        "/api/releases/v1/files/export",
        json={"mode": "copy", "folder": str(tmp_path), "with_copy": False},
    )
    assert again.status_code == 200, again.text


def test_correct_withdraw_yank_and_compare(client: TestClient):
    _study(client)
    client.post("/api/releases", json={"name": "v1", "title": "Survey"})
    fixed = client.patch("/api/releases/v1", json={"title": "The survey"})
    assert fixed.status_code == 200 and fixed.json()["title"] == "The survey"
    assert client.patch("/api/releases/v1", json={"doi": "nope"}).status_code == 422

    client.post(
        "/api/collections/south/records",
        json={"schema_name": "sample", "data": {"site": "more"}},
    )
    since = client.post("/api/releases/v1/compare").json()
    assert (since["added"], since["changed"], since["removed"]) == (1, 0, 0)
    assert since["collections"][0]["collection"] == "south"
    listed = client.get("/api/releases/v1/compare/records?kind=added").json()
    assert listed["total"] == 1 and listed["items"][0]["live"]
    assert client.get("/api/releases/v1/compare/records?kind=x").status_code == 422
    assert client.get("/api/releases/v1").json()["compare_in_background"] is False

    gone = client.post("/api/releases/v1/withdraw", json={"reason": "wrong units"})
    assert gone.status_code == 200 and gone.json()["withdrawn_reason"] == "wrong units"

    plan = client.get("/api/releases/v1/yank").json()
    assert plan["files"] == 2 and plan["kept_files"] == 1  # the photo is a record's
    yanked = client.post("/api/releases/v1/yank", json={"reason": "consent"})
    assert yanked.status_code == 200 and yanked.json()["yanked_reason"] == "consent"
    assert client.get("/api/releases/v1/bundle").status_code == 404
    assert client.post("/api/releases/v1/files/plan").status_code == 422
    assert client.get("/api/releases/nope").status_code == 404


def test_a_purge_plan_names_the_releases_keeping_files(client: TestClient):
    _study(client)
    client.post("/api/releases", json={"name": "v1", "title": "Survey"})
    (rec,) = client.get("/api/collections/north/records").json()["items"]
    assert client.delete(f"/api/records/{rec['id']}").status_code in (200, 204)
    plan = client.get(f"/api/records/{rec['id']}/purge-plan").json()
    assert plan == {"records": 1, "kept_by_releases": {"v1": 1}}


def test_a_release_is_written_straight_into_a_folder(client: TestClient, tmp_path):
    import zipfile

    _study(client)
    client.post("/api/releases", json={"name": "v1", "title": "Survey"})
    saved = client.post(
        "/api/releases/v1/save", json={"open": False, "folder": str(tmp_path)}
    )
    assert saved.status_code == 200, saved.text
    path = saved.json()["path"]
    assert path.startswith(str(tmp_path))
    with zipfile.ZipFile(path) as zf:
        assert "release.json" in zf.namelist()
    assert client.post("/api/releases/v9/save", json={"open": False}).status_code == 404
    assert (
        client.post(
            "/api/releases/v1/save",
            json={"folder": str(tmp_path / "nowhere"), "open": False},
        ).status_code
        == 404
    )


def test_the_bundle_lists_a_file_it_cannot_read_and_keeps_an_empty_one(
    client: TestClient,
):
    from civex.config import load_config
    from civex.context import build_local_context

    client.post("/api/schemas", json={"name": "sample"})
    client.post("/api/schemas/sample/fields", json={"name": "a", "type": "file"})
    client.post("/api/schemas/sample/fields", json={"name": "b", "type": "file"})
    gone = client.put(
        "/api/files/stream?filename=g.bin",
        content=b"gone",
        headers={"content-length": "4"},
    ).json()
    empty = client.put(
        "/api/files/stream?filename=e.bin",
        content=b"",
        headers={"content-length": "0"},
    ).json()
    client.post("/api/collections", json={"name": "c"})
    client.post(
        "/api/collections/c/records",
        json={"schema_name": "sample", "data": {"a": gone, "b": empty}},
    )
    made = client.post("/api/releases", json={"name": "v1", "title": "T"})
    assert made.status_code == 201
    ctx = build_local_context(load_config())
    ctx.file_svc.discard(gone["sha256"])
    ctx.commit()
    ctx.close()
    answer = client.get("/api/releases/v1/bundle")
    assert answer.status_code == 200
    with zipfile.ZipFile(io.BytesIO(answer.content)) as zf:
        manifest = json.loads(zf.read("bundle.json"))
        names = zf.namelist()
    assert manifest["files"]["missing"] == [gone["sha256"]]
    assert f"files/{empty['sha256']}" in names
