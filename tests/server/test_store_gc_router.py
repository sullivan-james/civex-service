"""HTTP-level tests for POST /api/store/gc."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_gc_dry_run_does_not_delete(client: TestClient) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post("/api/collections", json={"name": "study", "description": None})

    ctx = build_local_context(load_config())
    ref = ctx.file_svc._store.put(b"orphan", "orphan.txt")
    ctx.commit()
    ctx.close()

    resp = client.post("/api/store/gc", json={"grace_days": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["deleted_count"] == 1
    assert body["deleted"][0]["sha256"] == ref.sha256

    ctx2 = build_local_context(load_config())
    assert ctx2.file_svc._store.exists(ref.sha256)
    ctx2.close()


def test_gc_apply_deletes_unreferenced_objects(client: TestClient) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    client.post("/api/schemas", json={"name": "doc", "description": None})
    client.post("/api/collections", json={"name": "study", "description": None})

    ctx = build_local_context(load_config())
    ref = ctx.file_svc._store.put(b"orphan", "orphan.txt")
    ctx.commit()
    ctx.close()

    resp = client.post("/api/store/gc", json={"apply": True, "grace_days": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is False
    assert body["deleted_count"] == 1

    ctx2 = build_local_context(load_config())
    assert not ctx2.file_svc._store.exists(ref.sha256)
    ctx2.close()


def test_gc_defaults_to_dry_run_with_no_body(client: TestClient) -> None:
    resp = client.post("/api/store/gc", json={})
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True
    assert resp.json()["grace_days"] == 14


def test_volumes_report_state_and_adopt_restores_a_marker(
    client: TestClient, tmp_path
) -> None:
    drive = tmp_path / "usb"
    drive.mkdir()
    added = client.post("/api/store/volumes", json={"name": "usb", "path": str(drive)})
    assert added.status_code == 201
    assert added.json()["state"] == "online"

    (drive / ".civex-volume").unlink()
    listed = {v["name"]: v for v in client.get("/api/store/volumes").json()}
    assert listed["usb"]["state"] == "wrong_drive"
    assert listed["usb"]["available"] is False
    assert "adopt it" in listed["usb"]["fix"]

    adopted = client.post("/api/store/volumes/usb/adopt")
    assert adopted.status_code == 200
    assert adopted.json()["state"] == "online"

    assert client.post("/api/store/volumes/nope/adopt").status_code == 404


def _volume(client: TestClient, tmp_path, name: str = "archive") -> None:
    drive = tmp_path / name
    drive.mkdir()
    assert (
        client.post(
            "/api/store/volumes", json={"name": name, "path": str(drive)}
        ).status_code
        == 201
    )


def _collection(client: TestClient, name: str = "study") -> str:
    resp = client.post("/api/collections", json={"name": name, "description": None})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def test_placement_endpoints_and_uploads_follow_the_home(
    client: TestClient, tmp_path
) -> None:
    _volume(client, tmp_path)
    cid = _collection(client)

    put = client.put(f"/api/store/placement/{cid}", json={"volume": "archive"})
    assert put.status_code == 200
    assert put.json() == {
        "collection_id": cid,
        "collection_name": "study",
        "volume": "archive",
        "on_unavailable": "spill",
    }
    assert client.get("/api/store/placement").json() == [put.json()]

    homed = client.put(
        f"/api/files/stream?filename=a.txt&collection={cid}", content=b"homed bytes"
    )
    plain = client.put("/api/files/stream?filename=b.txt", content=b"queue bytes")
    assert homed.status_code == 201 and homed.json()["volume"] == "archive"
    assert plain.json()["volume"] == "default"

    # Dedup beats placement: the same bytes uploaded for the homed collection
    # are the existing copy on `default`, not a second one on `archive`.
    again = client.put(
        f"/api/files/stream?filename=c.txt&collection={cid}", content=b"queue bytes"
    )
    assert again.json()["volume"] == "default"
    multipart = client.post(
        f"/api/files?collection={cid}", files={"file": ("d.txt", b"homed bytes")}
    )
    assert multipart.json()["volume"] == "archive"

    assert client.delete(f"/api/store/placement/{cid}").status_code == 204
    assert client.get("/api/store/placement").json() == []


def test_placement_endpoint_errors(client: TestClient, tmp_path) -> None:
    _volume(client, tmp_path)
    cid = _collection(client)

    assert (
        client.put(
            "/api/store/placement/not-a-uuid", json={"volume": "archive"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/store/placement/{uuid.uuid4()}", json={"volume": "archive"}
        ).status_code
        == 404
    )
    assert (
        client.put(f"/api/store/placement/{cid}", json={"volume": "nope"}).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/store/placement/{cid}",
            json={"volume": "archive", "on_unavailable": "x"},
        ).status_code
        == 422
    )


def test_browse_lists_folders_and_places_to_start(client: TestClient, tmp_path) -> None:
    pick = tmp_path / "pick"
    for name in ("beta", "alpha"):
        (pick / name).mkdir(parents=True)
    (pick / "file.txt").write_text("x")

    resp = client.get("/api/store/browse", params={"path": str(pick)})

    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == pick.as_posix() and body["parent"] == tmp_path.as_posix()
    assert [e["name"] for e in body["entries"]] == ["alpha", "beta"]
    assert body["truncated"] is False
    assert "hint" in body  # None except where the platform has a known reason
    assert {"Project", "Home"} <= {loc["label"] for loc in body["locations"]}
    assert all("network" in loc for loc in body["locations"])


def test_browse_errors(client: TestClient, tmp_path) -> None:
    assert (
        client.get(
            "/api/store/browse", params={"path": str(tmp_path / "no")}
        ).status_code
        == 404
    )
    shaky = client.get("/api/store/browse", params={"path": "smb://nas/share"})
    assert shaky.status_code == 422 and "mount it first" in shaky.json()["detail"]


def test_create_folder_endpoint(client: TestClient, tmp_path) -> None:
    made = client.post(
        "/api/store/browse/folder", json={"parent": str(tmp_path), "name": "new"}
    )
    assert made.status_code == 201 and made.json() == {
        "path": (tmp_path / "new").as_posix()
    }
    assert (tmp_path / "new").is_dir()
    assert (
        client.post(
            "/api/store/browse/folder", json={"parent": str(tmp_path), "name": "new"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/store/browse/folder", json={"parent": str(tmp_path), "name": "a/b"}
        ).status_code
        == 422
    )


def test_inspect_endpoint_previews_what_add_would_do(
    client: TestClient, tmp_path
) -> None:
    ok = client.get("/api/store/inspect", params={"path": str(tmp_path / "fresh")})
    assert ok.status_code == 200
    body = ok.json()
    assert body["problems"] == [] and body["will_create"] is True
    assert body["is_network"] is False and body["warnings"]

    f = tmp_path / "file.txt"
    f.write_text("x")
    bad = client.get("/api/store/inspect", params={"path": str(f)}).json()
    assert any("is a file" in p for p in bad["problems"])
    # ...and adding it is refused with the same reason.
    refused = client.post("/api/store/volumes", json={"name": "f", "path": str(f)})
    assert refused.status_code == 422 and "is a file" in refused.json()["detail"]


def test_adding_a_volume_over_http_can_join_the_queue(
    client: TestClient, tmp_path
) -> None:
    (tmp_path / "q").mkdir()
    (tmp_path / "n").mkdir()
    for name, queued in (("q", True), ("n", False)):
        resp = client.post(
            "/api/store/volumes",
            json={"name": name, "path": str(tmp_path / name), "add_to_queue": queued},
        )
        assert resp.status_code == 201
        assert resp.json()["in_queue"] is queued


def test_downloading_a_file_on_an_unplugged_volume_says_so(
    client: TestClient, tmp_path
) -> None:
    drive = tmp_path / "usb"
    drive.mkdir()
    client.post("/api/store/volumes", json={"name": "usb", "path": str(drive)})
    cid = client.post(
        "/api/collections", json={"name": "study", "description": None}
    ).json()["id"]
    client.put(f"/api/store/placement/{cid}", json={"volume": "usb"})
    up = client.put(
        f"/api/files/stream?filename=a.txt&collection={cid}", content=b"on usb"
    )
    sha = up.json()["sha256"]
    assert client.get(f"/api/files/{sha}").status_code == 200

    drive.rename(tmp_path / "usb-unplugged")

    gone = client.get(f"/api/files/{sha}")
    assert gone.status_code == 503
    assert (
        "volume 'usb'" in gone.json()["detail"]
        and "isn't available" in gone.json()["detail"]
    )
    assert client.get(f"/api/files/{'00' * 32}").status_code == 404


def test_file_info_endpoint(client: TestClient, tmp_path) -> None:
    up = client.put("/api/files/stream?filename=a.txt", content=b"hello info")
    sha = up.json()["sha256"]

    info = client.get(f"/api/files/{sha}/info")

    assert info.status_code == 200
    body = info.json()
    assert body["size"] == len(b"hello info")
    assert [(c["volume"], c["state"], c["present"]) for c in body["copies"]] == [
        ("default", "online", True)
    ]
    assert body["records"] == 0 and body["collections"] == []
    assert client.get(f"/api/files/{'00' * 32}/info").status_code == 404


def test_gc_can_be_limited_to_one_volume(client: TestClient, tmp_path) -> None:
    from civex.config import load_config
    from civex.context import build_local_context

    ctx = build_local_context(load_config())
    for name in ("a", "b"):
        path = tmp_path / "mnt" / name
        path.mkdir(parents=True)
        ctx.store_svc.add_volume(name, str(path))
    ctx.store_svc.set_queue(["a"])
    on_a = ctx.file_svc._store.put(b"orphan on a", "a.txt")
    ctx.store_svc.set_queue(["b"])
    on_b = ctx.file_svc._store.put(b"orphan on b", "b.txt")
    ctx.commit()
    ctx.close()

    resp = client.post(
        "/api/store/gc", json={"apply": True, "grace_days": 0, "volume": "a"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["volume"] == "a"
    assert [o["sha256"] for o in body["deleted"]] == [on_a.sha256]
    ctx2 = build_local_context(load_config())
    assert not ctx2.file_svc._store.exists(on_a.sha256)
    assert ctx2.file_svc._store.exists(on_b.sha256)
    ctx2.close()


def test_gc_of_an_unknown_volume_is_404(client: TestClient) -> None:
    resp = client.post("/api/store/gc", json={"volume": "nowhere"})
    assert resp.status_code == 404
