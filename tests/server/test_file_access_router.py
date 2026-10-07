"""HTTP contract for /file-access: plan, export and zip of a selection of files."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest

from civex.context import AppContext


@pytest.fixture()
def study(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("name", "string")])
    make_schema(
        "recording", fields=[("rname", "string"), ("table", "file")], parent="encounter"
    )
    collection = make_collection("hb")
    enc = make_record("hb", "encounter", {"name": "Encounter 7"})

    def add(name: str, content: bytes, on: str | None = None):
        ref = ctx.file_svc.store_bytes(content, f"{name}.txt", on).to_dict()
        return make_record(
            "hb",
            "recording",
            {"rname": name, "table": ref},
            parent_record_id=str(enc.id),
        )

    class Study:
        pass

    s = Study()
    s.ctx, s.collection, s.enc, s.add = ctx, collection, enc, add
    return s


BODY = {"collection": "hb", "schema_name": "recording"}


def test_plan_names_files_by_hierarchy_and_pages_them(client, study) -> None:
    for n in ("a", "b", "c"):
        study.add(n, n.encode())

    resp = client.post("/api/file-access/plan", json={**BODY, "limit": 2})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3 and body["complete"] is True
    assert [i["path"] for i in body["items"]] == [
        "Encounter 7/a/a.txt",
        "Encounter 7/b/b.txt",
    ]
    assert (
        client.post(
            "/api/file-access/plan", json={**BODY, "include_items": False}
        ).json()["items"]
        == []
    )


def test_plan_under_a_record_starts_below_it(client, study) -> None:
    study.add("a", b"a")

    resp = client.post(
        "/api/file-access/plan",
        json={"within": str(study.enc.id), "schema_name": "recording"},
    )

    assert [i["path"] for i in resp.json()["items"]] == ["a/a.txt"]


def test_plan_errors(client, study) -> None:
    assert (
        client.post(
            "/api/file-access/plan", json={**BODY, "base": "ffffffff"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/file-access/plan", json={**BODY, "fields": ["nope"]}
        ).status_code
        == 422
    )


def test_export_builds_the_default_folder_and_opens_it_only_from_this_machine(
    client, study, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study.add("a", b"hello")
    opened: list[Path] = []
    monkeypatch.setattr(
        "civex.server.routers.file_access.fs_open.open_folder",
        lambda p: opened.append(p) or True,
    )

    # The test client is not "this machine": nothing is launched.
    away = client.post(
        "/api/file-access/export", json={**BODY, "name": "tables", "open": True}
    )
    assert away.status_code == 200, away.text
    assert away.json()["opened"] is False and opened == []

    monkeypatch.setattr(
        "civex.server.routers.file_access._from_this_machine", lambda request: True
    )
    here = client.post(
        "/api/file-access/export", json={**BODY, "name": "tables", "open": True}
    )

    dest = project_dir / "_civex" / "exports" / "tables"
    assert here.json()["opened"] is True and opened == [dest]
    assert here.json()["dest"] == str(dest)
    assert (dest / "Encounter 7" / "a" / "a.txt").read_bytes() == b"hello"
    assert here.json()["unchanged"] == 1  # the same name refreshed the same folder


def test_export_to_a_chosen_folder_and_a_foreign_folder_is_refused(
    client, study, tmp_path: Path
) -> None:
    study.add("a", b"hello")
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "keep.txt").write_text("x")

    refused = client.post("/api/file-access/export", json={**BODY, "dest": str(mine)})
    ok = client.post(
        "/api/file-access/export", json={**BODY, "dest": str(tmp_path / "fresh")}
    )

    assert refused.status_code == 422 and "other files" in refused.text
    assert ok.status_code == 200
    assert (tmp_path / "fresh" / "Encounter 7" / "a" / "a.txt").exists()


@pytest.fixture()
def archive(ctx: AppContext, study, tmp_path_factory: pytest.TempPathFactory):
    """A drive outside the project, home to the collection's new files."""
    drive = tmp_path_factory.mktemp("drives") / "archive"
    drive.mkdir()
    ctx.store_svc.add_volume("archive", str(drive))
    ctx.store_svc.set_placement(str(study.collection.id), "archive")
    study.add("near", b"on default")
    study.add("far", b"on archive", on=str(study.collection.id))
    return drive


@pytest.fixture()
def unplugged(archive: Path):
    archive.rename(archive.with_name("archive-unplugged"))


def test_export_with_files_out_of_reach_builds_nothing_and_says_what(
    client, archive, unplugged, project_dir: Path
) -> None:
    resp = client.post("/api/file-access/export", json={**BODY, "name": "t"})

    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "files_unavailable"
    assert body["plan"]["available"] == 1 and body["plan"]["total"] == 2
    assert body["plan"]["unavailable"][0]["volume"] == "archive"
    assert body["plan"]["items"] == []  # the groups say it; the list would be noise
    assert not (project_dir / "_civex" / "exports" / "t").exists()


def test_export_can_go_ahead_with_what_is_reachable(
    client, unplugged, project_dir
) -> None:
    resp = client.post(
        "/api/file-access/export", json={**BODY, "name": "t", "allow_partial": True}
    )

    body = resp.json()
    assert resp.status_code == 200 and body["complete"] is False
    assert [m["path"] for m in body["missing"]] == ["Encounter 7/far/far.txt"]
    assert (project_dir / "_civex" / "exports" / "t" / "MISSING.txt").exists()


def test_zip_has_the_same_paths_as_an_export(client, study) -> None:
    study.add("a", b"hello")

    resp = client.post("/api/file-access/zip", json=BODY)

    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.namelist() == ["Encounter 7/a/a.txt"]
    assert zf.read("Encounter 7/a/a.txt") == b"hello"


def test_zip_refuses_a_partial_selection_unless_told_otherwise(
    client, unplugged
) -> None:
    refused = client.post("/api/file-access/zip", json=BODY)
    allowed = client.post("/api/file-access/zip", json={**BODY, "allow_partial": True})

    assert refused.status_code == 409
    zf = zipfile.ZipFile(io.BytesIO(allowed.content))
    assert sorted(zf.namelist()) == ["Encounter 7/near/near.txt", "MISSING.txt"]
    assert "far.txt" in zf.read("MISSING.txt").decode()


def test_files_on_several_drives_cannot_be_linked_but_can_be_copied_to_one(
    client, archive: Path
) -> None:
    refused = client.post("/api/file-access/export", json={**BODY, "name": "t"})
    copied = client.post(
        "/api/file-access/export",
        json={**BODY, "name": "t", "mode": "copy", "volume": "archive"},
    )

    assert refused.status_code == 409
    body = refused.json()
    assert body["code"] == "files_scattered" and "2 drives" in body["detail"]
    assert {v["volume"] for v in body["plan"]["by_volume"]} == {"default", "archive"}
    assert copied.status_code == 200, copied.text
    assert copied.json()["location"] == "archive" and copied.json()["copied"] == 2
    assert (archive / "_exports" / "t" / "Encounter 7" / "far" / "far.txt").exists()


def test_plan_says_whether_the_files_can_share_a_linked_folder(
    client, study, archive: Path
) -> None:
    plan = client.post("/api/file-access/plan", json=BODY).json()

    assert plan["scattered"] is True and plan["link_volume"] is None
    assert [v["files"] for v in plan["by_volume"]] == [1, 1]


def test_a_drive_that_cannot_link_answers_409(
    client, study, monkeypatch: pytest.MonkeyPatch
) -> None:
    study.add("a", b"hello")

    def refuse(*a, **k):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr("civex.services.file_access_service.os.link", refuse)
    resp = client.post("/api/file-access/export", json={**BODY, "name": "t"})

    assert resp.status_code == 409
    assert resp.json()["code"] == "links_not_possible"


def test_exports_are_listed_and_removed(client, study, project_dir: Path) -> None:
    study.add("a", b"hello")
    made = client.post(
        "/api/file-access/export", json={**BODY, "name": "t", "mode": "copy"}
    ).json()

    listed = client.get("/api/file-access/exports").json()
    gone = client.post(
        "/api/file-access/exports/remove", json={"paths": [made["dest"]]}
    )

    assert [e["name"] for e in listed] == ["t"]
    assert listed[0]["location"] == "project" and listed[0]["copied"] == 1
    assert gone.status_code == 200
    assert gone.json()["results"][0]["freed_bytes"] == 5
    assert gone.json()["errors"] == []
    assert not Path(made["dest"]).exists()
    assert client.get("/api/file-access/exports").json() == []


def test_removing_something_that_is_not_an_export_is_refused(
    client, tmp_path: Path
) -> None:
    folder = tmp_path / "mine"
    folder.mkdir()
    (folder / "x.txt").write_text("x")

    resp = client.post("/api/file-access/exports/remove", json={"paths": [str(folder)]})

    assert resp.status_code == 200
    assert resp.json()["results"] == []
    assert "not a folder a civex export made" in resp.json()["errors"][0]["error"]
    assert (folder / "x.txt").exists()


def _wait_done(client, transfer_id: str) -> dict:
    for _ in range(100):
        got = client.get(f"/api/store/transfers/{transfer_id}").json()
        if got["status"] == "completed":
            return got
        time.sleep(0.1)
    raise AssertionError(f"never completed: {got['status']}")


def test_gathering_a_selection_onto_one_drive_makes_it_linkable(
    client, study, archive: Path
) -> None:
    refused = client.post("/api/file-access/export", json={**BODY, "name": "t"})
    assert refused.status_code == 409

    started = client.post("/api/file-access/gather", json={**BODY, "volume": "archive"})

    assert started.status_code == 202, started.text
    assert started.json()["files"] == 1 and started.json()["volume"] == "archive"
    done = _wait_done(client, started.json()["transfer_id"])
    assert done["kind"] == "files" and done["progress"]["files_done"] == 1
    plan = client.post("/api/file-access/plan", json=BODY).json()
    assert plan["scattered"] is False and plan["link_volume"] == "archive"
    linked = client.post("/api/file-access/export", json={**BODY, "name": "t"})
    assert linked.status_code == 200 and linked.json()["location"] == "archive"
    assert linked.json()["linked"] == 2


def test_gathering_what_is_already_there_is_refused(client, study) -> None:
    study.add("a", b"hello")

    resp = client.post("/api/file-access/gather", json={**BODY, "volume": "default"})

    assert resp.status_code == 422
    assert "already on 'default'" in resp.json()["detail"]


def test_gathering_onto_an_unknown_drive_is_not_found(client, study) -> None:
    study.add("a", b"hello")

    resp = client.post("/api/file-access/gather", json={**BODY, "volume": "nowhere"})

    assert resp.status_code == 404


def test_a_flat_layout_gives_every_file_a_top_level_path(client, study) -> None:
    study.add("a", b"a")
    study.add("b", b"b")

    resp = client.post("/api/file-access/plan", json={**BODY, "layout": "flat"})
    bad = client.post("/api/file-access/plan", json={**BODY, "layout": "spiral"})

    assert [i["path"] for i in resp.json()["items"]] == ["a.txt", "b.txt"]
    assert bad.status_code == 422


def test_a_flat_export_and_zip_use_the_same_flat_paths(
    client, study, project_dir: Path
) -> None:
    study.add("a", b"hello")

    made = client.post(
        "/api/file-access/export",
        json={**BODY, "name": "flat", "layout": "flat", "mode": "copy"},
    )
    zipped = client.post("/api/file-access/zip", json={**BODY, "layout": "flat"})

    assert made.status_code == 200, made.text
    assert (
        project_dir / "_civex" / "exports" / "flat" / "a.txt"
    ).read_bytes() == b"hello"
    assert zipfile.ZipFile(io.BytesIO(zipped.content)).namelist() == ["a.txt"]


def test_a_saved_view_is_a_selection_with_its_layout(client, study, ctx) -> None:
    study.add("a", b"a")
    study.add("b", b"b")
    ctx.view_svc.create(
        "recording", "tables", columns=["rname", "table"], files_layout="flat"
    )
    ctx.commit()

    plan = client.post("/api/file-access/plan", json={"view": "recording/tables"})
    overridden = client.post(
        "/api/file-access/plan", json={"view": "recording/tables", "layout": "tree"}
    )

    assert [i["path"] for i in plan.json()["items"]] == ["a.txt", "b.txt"]
    assert [i["path"] for i in overridden.json()["items"]] == [
        "Encounter 7/a/a.txt",
        "Encounter 7/b/b.txt",
    ]


def test_a_view_can_be_exported_and_zipped_like_any_selection(
    client, study, ctx, project_dir: Path
) -> None:
    study.add("a", b"hello")
    ctx.view_svc.create("recording", "tables", columns=["table"], files_layout="flat")
    ctx.commit()

    made = client.post(
        "/api/file-access/export",
        json={"view": "recording/tables", "name": "from-view", "mode": "copy"},
    )
    zipped = client.post("/api/file-access/zip", json={"view": "recording/tables"})

    assert made.status_code == 200, made.text
    assert (project_dir / "_civex" / "exports" / "from-view" / "a.txt").exists()
    assert zipfile.ZipFile(io.BytesIO(zipped.content)).namelist() == ["a.txt"]


def test_a_view_that_cannot_be_used_is_refused_clearly(client, study, ctx) -> None:
    ctx.view_svc.create("encounter", "names", columns=["name"])
    ctx.commit()

    no_files = client.post("/api/file-access/plan", json={"view": "encounter/names"})
    unknown = client.post("/api/file-access/plan", json={"view": "recording/nope"})
    malformed = client.post("/api/file-access/plan", json={"view": "tables"})

    assert no_files.status_code == 422 and "no file columns" in no_files.text
    assert unknown.status_code == 404
    assert malformed.status_code == 422


def test_the_grouped_layout_is_accepted_everywhere_a_layout_is(client, study) -> None:
    study.add("a", b"a")

    resp = client.post(
        "/api/file-access/plan",
        json={**BODY, "layout": "grouped", "within": str(study.enc.id)},
    )
    made = client.post(
        "/api/schemas/recording/views",
        json={"name": "g", "columns": ["table"], "files_layout": "grouped"},
    )

    # Below the encounter, the recordings that hold the files share a folder.
    assert [i["path"] for i in resp.json()["items"]] == ["Recordings/a.txt"]
    assert made.status_code == 201 and made.json()["files_layout"] == "grouped"


def test_a_preview_can_be_limited_to_some_kinds_of_record(client, study) -> None:
    study.add("a", b"a")

    inside = client.post(
        "/api/file-access/plan",
        json={"collection": "hb", "kinds": ["recording"], "layout": "flat"},
    )
    elsewhere = client.post(
        "/api/file-access/plan",
        json={"collection": "hb", "kinds": ["encounter"], "layout": "flat"},
    )

    assert [i["path"] for i in inside.json()["items"]] == ["a.txt"]
    # An encounter holds no files, so nothing is taken from it.
    assert elsewhere.status_code == 200 and elsewhere.json()["items"] == []


def test_a_selection_can_take_everything_beneath_the_records_it_names(
    client, study
) -> None:
    study.add("a", b"a")

    alone = client.post(
        "/api/file-access/plan", json={"collection": "hb", "schema_name": "encounter"}
    )
    below = client.post(
        "/api/file-access/plan",
        json={"collection": "hb", "schema_name": "encounter", "below": True},
    )

    assert alone.json()["items"] == []
    assert [i["path"] for i in below.json()["items"]] == ["Encounter 7/a/a.txt"]


# -- progress ---------------------------------------------------------------------------

PROGRESS_ID = "3f2b8c1e-9d4a-4e1f-8a7b-1c2d3e4f5a6b"


@pytest.fixture(autouse=True)
def _forget_progress() -> None:
    """The registry is process-wide; each test starts with nothing in it."""
    from civex.services.progress import registry

    registry._states.clear()


def test_a_tagged_request_can_be_followed_while_and_after_it_runs(
    client, study
) -> None:
    study.add("a", b"a")
    study.add("b", b"b")

    made = client.post(
        "/api/file-access/export",
        json={**BODY, "name": "t", "mode": "copy"},
        headers={"X-Civex-Progress": PROGRESS_ID},
    )
    state = client.get(f"/api/file-access/progress/{PROGRESS_ID}")

    assert made.status_code == 200, made.text
    assert state.status_code == 200
    assert state.json() == {
        "phase": "Copying the files",
        "done": 2,
        "total": 2,
        "finished": True,
        "error": None,
    }


def test_a_plan_can_be_followed_too(client, study) -> None:
    study.add("a", b"a")

    client.post(
        "/api/file-access/plan",
        json=BODY,
        headers={"X-Civex-Progress": PROGRESS_ID},
    )
    state = client.get(f"/api/file-access/progress/{PROGRESS_ID}").json()

    assert state["finished"] is True and state["error"] is None
    assert state["phase"] == "Working out the folders"


def test_an_unknown_id_says_nothing_is_reporting(client) -> None:
    resp = client.get("/api/file-access/progress/never-heard-of-it")

    assert resp.status_code == 404


def test_a_request_without_the_header_reports_nothing(client, study) -> None:
    study.add("a", b"a")

    client.post("/api/file-access/plan", json=BODY)

    assert client.get(f"/api/file-access/progress/{PROGRESS_ID}").status_code == 404


def test_a_header_that_is_not_a_plain_id_is_ignored(client, study) -> None:
    study.add("a", b"a")

    resp = client.post(
        "/api/file-access/plan",
        json=BODY,
        headers={"X-Civex-Progress": "../../etc/passwd"},
    )

    assert resp.status_code == 200  # the request itself is unaffected


def test_a_request_that_fails_says_so_in_its_progress(client, study) -> None:
    resp = client.post(
        "/api/file-access/plan",
        json={**BODY, "fields": ["nope"]},
        headers={"X-Civex-Progress": PROGRESS_ID},
    )
    state = client.get(f"/api/file-access/progress/{PROGRESS_ID}").json()

    assert resp.status_code == 422
    assert state["finished"] is True


def test_a_table_comes_in_the_zip_beside_the_files(client, study) -> None:
    study.add("a", b"a")
    study.add("b", b"b")

    resp = client.post(
        "/api/file-access/zip",
        json={**BODY, "tables": [{"format": "csv", "columns": ["rname", "table"]}]},
    )

    assert resp.status_code == 200, resp.text
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert sorted(zf.namelist()) == [
        "Encounter 7/a/a.txt",
        "Encounter 7/b/b.txt",
        "Recordings.csv",
    ]
    assert zf.read("Recordings.csv").decode().splitlines() == [
        "rname,table",
        "a,Encounter 7/a/a.txt",
        "b,Encounter 7/b/b.txt",
    ]


def test_a_table_alone_downloads_as_that_one_file(client, study) -> None:
    study.add("a", b"a")

    resp = client.post(
        "/api/file-access/zip",
        json={
            **BODY,
            "files": False,
            "name": "names",
            "tables": [{"format": "jsonl", "columns": ["rname"]}],
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert "names.jsonl" in resp.headers["content-disposition"]
    assert resp.text.strip() == '{"rname": "a"}'


def test_the_order_asked_for_is_the_order_of_the_rows(client, study) -> None:
    for n in ("a", "b", "c"):
        study.add(n, n.encode())

    resp = client.post(
        "/api/file-access/zip",
        json={
            **BODY,
            "files": False,
            "tables": [{"format": "csv", "columns": ["rname"]}],
            "sort": [{"field": "rname", "direction": "desc"}],
        },
    )

    assert resp.text.splitlines() == ["rname", "c", "b", "a"]


def test_without_files_a_table_is_needed(client, study) -> None:
    resp = client.post("/api/file-access/zip", json={**BODY, "files": False})

    assert resp.status_code == 422


def test_the_plan_lists_the_tables_an_export_would_make(client, study) -> None:
    study.add("a", b"a")

    plan = client.post(
        "/api/file-access/plan",
        json={**BODY, "tables": [{"format": "xlsx"}], "include_items": False},
    ).json()

    assert plan["tables"] == [
        {
            "name": "Recordings.xlsx",
            "folder": "",
            "path": "Recordings.xlsx",
            "kind": "recording",
            "rows": 1,
            "columns": ["id", "rname", "table", "name"],
            "format": "xlsx",
            "shape": "rows",
        }
    ]


def test_a_table_can_be_written_in_each_folder_and_the_plan_says_where(
    client, study
) -> None:
    for n in ("a", "b"):
        study.add(n, n.encode())

    plan = client.post(
        "/api/file-access/plan",
        json={
            **BODY,
            "tables": [
                {
                    "format": "csv",
                    "columns": ["rname"],
                    "kind": "recording",
                    "where": "recording",
                    "shape": "fields",
                }
            ],
            "include_items": False,
        },
    ).json()

    assert [(t["path"], t["rows"], t["shape"]) for t in plan["tables"]] == [
        ("Encounter 7/a/Metadata.csv", 1, "fields"),  # beside a's file
        ("Encounter 7/b/Metadata.csv", 1, "fields"),
    ]


def test_a_table_in_each_folder_is_refused_with_another_layout(client, study) -> None:
    study.add("a", b"a")

    resp = client.post(
        "/api/file-access/plan",
        json={
            **BODY,
            "layout": "flat",
            "tables": [{"kind": "recording", "where": "recording"}],
        },
    )

    assert resp.status_code == 422
    assert "folder per record" in resp.text


def test_a_table_that_breaks_its_own_rules_is_refused(client, study) -> None:
    resp = client.post(
        "/api/file-access/plan",
        json={**BODY, "tables": [{"kind": "recording", "shape": "fields"}]},
    )

    assert resp.status_code == 422


def test_files_of_a_selection_are_listed_by_place_and_acted_on(
    client, ctx, make_schema, make_collection, make_record
):
    make_schema("doc", fields=[("title", "string"), ("scan", "file")])
    make_collection("papers")
    ref = ctx.file_svc.store_bytes(b"pages", "scan.pdf")
    make_record("papers", "doc", {"title": "A", "scan": ref.to_dict()})
    ctx.commit()

    listed = client.post("/api/file-access/files", json={"collection": "papers"}).json()
    assert listed["total"] == 1
    assert listed["summary"] == [
        {
            "place": "default",
            "kind": "drive",
            "files": 1,
            "bytes": 5,
            "reason": "",
            "fix": "",
        }
    ]
    assert listed["items"][0]["place"] == "default"
    assert listed["items"][0]["place_kind"] == "drive"
    empty = client.post(
        "/api/file-access/files", json={"collection": "papers", "place": "server"}
    ).json()
    assert empty["total"] == 0

    already = client.post(
        "/api/file-access/gather", json={"collection": "papers", "volume": "default"}
    )
    assert already.status_code == 422
    nowhere = client.post("/api/file-access/free-up", json={"collection": "papers"})
    assert nowhere.status_code == 422  # follows no server
