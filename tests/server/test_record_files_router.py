"""A file and the record change it is for, as one request:
`PUT /records/{id}/files/{field}` and `POST /collections/{c}/records/with-files`.
A refused save stores nothing; a save that goes in fills fields from the
file's name in the same save."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex.context import AppContext

READING = b"time,value\n09:30,1\n"
SHA = hashlib.sha256(READING).hexdigest()


@pytest.fixture()
def samples(ctx: AppContext, make_schema, make_collection):
    """A `sample` with a `reading` file, `taken_at` read from its name and
    unique, and `photos` (a list)."""
    make_collection("survey")
    make_schema("sample", fields=[("reading", "file"), ("photos", "file_list")])
    ctx.schema_svc.add_field(
        "sample",
        "taken_at",
        "datetime",
        restrictions={
            "from_filename": {"field": "reading", "pattern": "YYYYMMDD_HHmmSS"}
        },
    )
    ctx.schema_svc.set_unique_keys("sample", [["taken_at"]])
    ctx.commit()


def _blob_path(project_dir: Path, sha: str) -> Path:
    return project_dir / "_civex" / "objects" / sha[:2] / sha[2:]


def _new_sample(client: TestClient, data: dict | None = None) -> dict:
    r = client.post(
        "/api/collections/survey/records",
        json={"schema_name": "sample", "data": data or {}},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _attach(client: TestClient, record_id: str, field: str, name: str, body: bytes):
    return client.put(
        f"/api/records/{record_id}/files/{field}?name={name}&size={len(body)}",
        content=body,
        headers={"content-length": str(len(body))},
    )


def test_a_file_is_stored_and_the_record_saved_in_one_request(
    client: TestClient, project_dir: Path, samples
):
    record = _new_sample(client)
    r = _attach(client, record["id"], "reading", "20240315_093000.csv", READING)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["reading"]["sha256"] == SHA
    assert data["reading"]["filename"] == "20240315_093000.csv"
    # Filled from the file's name, in the same save.
    assert data["taken_at"] == "2024-03-15T09:30:00+00:00"
    assert _blob_path(project_dir, SHA).exists()
    assert client.get(f"/api/records/{record['id']}").json()["data"] == data


def test_a_refused_save_stores_nothing(client: TestClient, project_dir: Path, samples):
    first = _new_sample(client)
    assert (
        _attach(
            client, first["id"], "reading", "20240315_093000.csv", READING
        ).status_code
        == 200
    )
    second = _new_sample(client, {"photos": []})
    before = client.get(f"/api/records/{second['id']}").json()["data"]

    other = b"a different reading, same time in its name"
    r = _attach(client, second["id"], "reading", "20240315_093000.csv", other)

    assert r.status_code == 422
    # The field error, as PATCH /records/{id} gives it.
    assert "taken_at" in r.json()["detail"]
    assert not _blob_path(project_dir, hashlib.sha256(other).hexdigest()).exists()
    assert client.get(f"/api/records/{second['id']}").json()["data"] == before


def test_content_that_was_already_stored_is_kept_when_the_save_is_refused(
    client: TestClient, project_dir: Path, samples
):
    first = _new_sample(client)
    assert (
        _attach(
            client, first["id"], "reading", "20240315_093000.csv", READING
        ).status_code
        == 200
    )
    second = _new_sample(client)

    r = _attach(client, second["id"], "reading", "20240315_093000.csv", READING)

    assert r.status_code == 422
    assert _blob_path(project_dir, SHA).exists()  # the first record's file
    assert client.get(f"/api/files/{SHA}").status_code == 200


def test_a_file_list_takes_each_file_after_the_last(client: TestClient, samples):
    record = _new_sample(client)
    r1 = _attach(client, record["id"], "photos", "a.jpg", b"aaa")
    r2 = _attach(client, record["id"], "photos", "b.jpg", b"bbb")
    assert r1.status_code == 200 and r2.status_code == 200
    names = [p["filename"] for p in r2.json()["data"]["photos"]]
    assert names == ["a.jpg", "b.jpg"]
    # A single-file field is replaced instead.
    _attach(client, record["id"], "reading", "20240315_093000.csv", READING)
    r3 = _attach(client, record["id"], "reading", "20240316_093000.csv", b"x")
    assert r3.json()["data"]["reading"]["filename"] == "20240316_093000.csv"


def test_a_field_that_is_not_a_file_or_not_there_is_refused(
    client: TestClient, samples
):
    record = _new_sample(client)
    assert _attach(client, record["id"], "taken_at", "x.csv", b"x").status_code == 422
    assert _attach(client, record["id"], "nope", "x.csv", b"x").status_code == 404
    assert _attach(client, "00000000", "reading", "x.csv", b"x").status_code == 404


def test_a_record_and_its_files_are_created_together(
    client: TestClient, project_dir: Path, samples
):
    r = client.post(
        "/api/collections/survey/records/with-files",
        data={"record": json.dumps({"schema_name": "sample", "data": {}})},
        files=[
            ("reading", ("20240315_093000.csv", READING, "text/csv")),
            ("photos", ("a.jpg", b"aaa", "image/jpeg")),
            ("photos", ("b.jpg", b"bbb", "image/jpeg")),
        ],
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["reading"]["sha256"] == SHA
    assert data["taken_at"] == "2024-03-15T09:30:00+00:00"
    assert [p["filename"] for p in data["photos"]] == ["a.jpg", "b.jpg"]
    assert _blob_path(project_dir, SHA).exists()


def test_a_refused_creation_makes_no_record_and_keeps_no_new_file(
    client: TestClient, project_dir: Path, samples
):
    first = _new_sample(client)
    assert (
        _attach(
            client, first["id"], "reading", "20240315_093000.csv", READING
        ).status_code
        == 200
    )
    other = b"other bytes"
    photo = b"a photo"

    r = client.post(
        "/api/collections/survey/records/with-files",
        data={"record": json.dumps({"schema_name": "sample", "data": {}})},
        files=[
            ("reading", ("20240315_093000.csv", other, "text/csv")),
            ("photos", ("a.jpg", photo, "image/jpeg")),
        ],
    )

    assert r.status_code == 422
    assert "taken_at" in r.json()["detail"]
    for body in (other, photo):
        assert not _blob_path(project_dir, hashlib.sha256(body).hexdigest()).exists()
    assert _blob_path(project_dir, SHA).exists()
    listed = client.get("/api/collections/survey/records").json()
    assert listed["total"] == 1


def test_the_record_part_and_the_field_names_are_checked(client: TestClient, samples):
    r = client.post(
        "/api/collections/survey/records/with-files",
        data={"record": "not json"},
        files=[("reading", ("a.csv", b"x", "text/csv"))],
    )
    assert r.status_code == 422
    r = client.post(
        "/api/collections/survey/records/with-files",
        data={"record": json.dumps({"schema_name": "sample"})},
        files=[("taken_at", ("a.csv", b"x", "text/csv"))],
    )
    assert r.status_code == 422
    r = client.post(
        "/api/collections/nowhere/records/with-files",
        data={"record": json.dumps({"schema_name": "sample"})},
    )
    assert r.status_code == 404
