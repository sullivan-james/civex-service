"""HTTP contract for GET /records/{id}/files.zip."""
from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient


def _upload(client: TestClient, filename: str, content: bytes) -> dict:
    resp = client.post(
        "/api/files", files={"file": (filename, io.BytesIO(content), "text/plain")}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_export_record_files_zip_bundles_every_file(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post(
        "/api/schemas/invoice/fields",
        json={"name": "scan", "type": "file"},
    )
    client.post(
        "/api/schemas/invoice/fields",
        json={"name": "attachments", "type": "file_list"},
    )
    client.post("/api/collections", json={"name": "study"})

    scan = _upload(client, "scan.pdf", b"scan-bytes")
    a1 = _upload(client, "one.txt", b"one-bytes")
    a2 = _upload(client, "two.txt", b"two-bytes")

    record = client.post(
        "/api/collections/study/records",
        json={
            "schema_name": "invoice",
            "data": {"scan": scan, "attachments": [a1, a2]},
        },
    ).json()

    resp = client.get(f"/api/records/{record['id']}/files.zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert set(zf.namelist()) == {"scan.pdf", "one.txt", "two.txt"}
    assert zf.read("scan.pdf") == b"scan-bytes"
    assert zf.read("one.txt") == b"one-bytes"


def test_export_record_files_zip_scoped_to_field(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post("/api/schemas/invoice/fields", json={"name": "scan", "type": "file"})
    client.post(
        "/api/schemas/invoice/fields",
        json={"name": "attachments", "type": "file_list"},
    )
    client.post("/api/collections", json={"name": "study"})

    scan = _upload(client, "scan.pdf", b"scan-bytes")
    a1 = _upload(client, "one.txt", b"one-bytes")

    record = client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"scan": scan, "attachments": [a1]}},
    ).json()

    resp = client.get(
        f"/api/records/{record['id']}/files.zip", params={"field": "attachments"}
    )
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.namelist() == ["one.txt"]


def test_export_record_files_zip_handles_name_collisions(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post(
        "/api/schemas/invoice/fields",
        json={"name": "attachments", "type": "file_list"},
    )
    client.post("/api/collections", json={"name": "study"})

    a1 = _upload(client, "report.pdf", b"first")
    a2 = _upload(client, "report.pdf", b"second")

    record = client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"attachments": [a1, a2]}},
    ).json()

    resp = client.get(f"/api/records/{record['id']}/files.zip")
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert set(zf.namelist()) == {"report.pdf", "report (1).pdf"}
    assert zf.read("report.pdf") == b"first"
    assert zf.read("report (1).pdf") == b"second"


def test_export_record_files_zip_404_for_missing_record(client: TestClient) -> None:
    resp = client.get("/api/records/deadbeef/files.zip")
    assert resp.status_code == 404


def test_export_record_files_zip_404_for_unknown_field(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post("/api/collections", json={"name": "study"})
    record = client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {}},
    ).json()

    resp = client.get(
        f"/api/records/{record['id']}/files.zip", params={"field": "nope"}
    )
    assert resp.status_code == 404


def test_export_record_files_zip_422_for_non_file_field(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post(
        "/api/schemas/invoice/fields", json={"name": "subject", "type": "string"}
    )
    client.post("/api/collections", json={"name": "study"})
    record = client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {"subject": "S01"}},
    ).json()

    resp = client.get(
        f"/api/records/{record['id']}/files.zip", params={"field": "subject"}
    )
    assert resp.status_code == 422


def test_export_record_files_zip_empty_when_no_files(client: TestClient) -> None:
    client.post("/api/schemas", json={"name": "invoice"})
    client.post("/api/schemas/invoice/fields", json={"name": "scan", "type": "file"})
    client.post("/api/collections", json={"name": "study"})
    record = client.post(
        "/api/collections/study/records",
        json={"schema_name": "invoice", "data": {}},
    ).json()

    resp = client.get(f"/api/records/{record['id']}/files.zip")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.namelist() == []
