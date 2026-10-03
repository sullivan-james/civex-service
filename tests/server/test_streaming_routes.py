"""Uploads, downloads and exports go through disk in chunks."""

from __future__ import annotations

import hashlib

import yaml
from fastapi.testclient import TestClient


def test_multipart_upload_and_download_roundtrip(client: TestClient) -> None:
    payload = b"m" * (3 * 1024 * 1024 + 17)  # several chunks, ragged tail
    sha = hashlib.sha256(payload).hexdigest()

    resp = client.post("/api/files", files={"file": ("big.bin", payload)})
    assert resp.status_code == 201
    assert resp.json()["sha256"] == sha
    assert resp.json()["size"] == len(payload)

    dl = client.get(f"/api/files/{sha}?filename=renamed.bin")
    assert dl.status_code == 200
    assert dl.content == payload
    assert "renamed.bin" in dl.headers["content-disposition"]
    assert dl.headers["content-disposition"].startswith("attachment")


def test_download_without_filename_sends_no_disposition(client: TestClient) -> None:
    sha = client.post("/api/files", files={"file": ("a.txt", b"hi")}).json()["sha256"]
    dl = client.get(f"/api/files/{sha}")
    assert dl.content == b"hi"
    assert "content-disposition" not in dl.headers


def test_download_supports_range_requests(client: TestClient) -> None:
    payload = bytes(range(256)) * 100
    sha = client.post("/api/files", files={"file": ("r.bin", payload)}).json()["sha256"]
    part = client.get(f"/api/files/{sha}", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == payload[10:20]


def test_download_missing_object_is_404(client: TestClient) -> None:
    assert client.get(f"/api/files/{'0' * 64}").status_code == 404


def test_dump_is_one_valid_yaml_document_with_paged_records(
    client: TestClient, ctx, make_schema, make_collection
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    make_collection("study")
    for i in range(7):
        ctx.record_svc.add("study", "trial", {"subject": f"S{i}"})
    ctx.commit()

    resp = client.get("/api/dump")
    assert resp.status_code == 200
    doc = yaml.safe_load(resp.content)
    assert list(doc)[:5] == [
        "civex_version",
        "exported_at",
        "schemas",
        "datasets",
        "records",
    ]
    assert sorted(r["data"]["subject"] for r in doc["records"]) == [
        f"S{i}" for i in range(7)
    ]

    empty = yaml.safe_load(client.get("/api/dump?no_data=true").content)
    assert empty["records"] == []


def test_trash_list_is_paginated(
    client: TestClient, ctx, make_schema, make_collection
) -> None:
    make_schema("trial", fields=[("subject", "string")])
    make_collection("study")
    ids = [
        ctx.record_svc.add("study", "trial", {"subject": f"S{i}"}).id for i in range(5)
    ]
    ctx.commit()
    for rid in ids:
        ctx.record_svc.delete(str(rid))
    ctx.commit()

    page1 = client.get("/api/records/deleted?limit=2&offset=0").json()
    page2 = client.get("/api/records/deleted?limit=2&offset=2").json()
    page3 = client.get("/api/records/deleted?limit=2&offset=4").json()
    got = [r["id"] for r in page1 + page2 + page3]
    assert len(got) == 5 and set(got) == {str(i) for i in ids}
