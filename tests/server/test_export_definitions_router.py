"""HTTP contract for exports saved with a schema, and running them."""

from __future__ import annotations

import pytest

from civex.context import AppContext


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("name", "string")])
    make_schema(
        "recording", fields=[("rname", "string"), ("audio", "file")], parent="encounter"
    )
    make_schema(
        "selection",
        fields=[("sname", "string"), ("contour", "file"), ("table", "file")],
        parent="recording",
    )
    make_collection("hb", schemas=["encounter", "recording", "selection"])
    e7 = make_record("hb", "encounter", {"name": "Encounter 7"})
    rec = make_record(
        "hb", "recording", {"rname": "Rec A"}, parent_record_id=str(e7.id)
    )
    for name in ("s1", "s2"):
        make_record(
            "hb",
            "selection",
            {
                "sname": name,
                "contour": ctx.file_svc.store_bytes(
                    name.encode(), f"{name}.contour"
                ).to_dict(),
                "table": ctx.file_svc.store_bytes(
                    name.encode() + b"t", f"{name}.table"
                ).to_dict(),
            },
            parent_record_id=str(rec.id),
        )

    class Tree:
        pass

    t = Tree()
    t.e7, t.rec = e7, rec
    return t


BODY = {
    "name": "Contours",
    "holder": "selection",
    "fields": ["contour"],
    "files_layout": "flat",
}


def test_an_export_is_created_read_listed_changed_and_deleted(client, tree) -> None:
    made = client.post("/api/schemas/encounter/exports", json=BODY)
    assert made.status_code == 201, made.text
    assert made.json() | {"id": "", "schema_id": ""} == {
        "id": "",
        "schema_id": "",
        "schema_name": "encounter",
        "name": "Contours",
        "holder": "selection",
        "fields": ["contour"],
        "filter_tree": None,
        "files_layout": "flat",
        "include_files": True,
        "tables": [],
    }

    listed = client.get("/api/schemas/encounter/exports").json()
    one = client.get("/api/schemas/encounter/exports/Contours")
    changed = client.patch(
        "/api/schemas/encounter/exports/Contours",
        json={"files_layout": "grouped", "rename": "Contour files"},
    )
    gone = client.delete("/api/schemas/encounter/exports/Contour files")

    assert [e["name"] for e in listed] == ["Contours"]
    assert one.status_code == 200 and one.json()["fields"] == ["contour"]
    assert changed.json()["files_layout"] == "grouped"
    assert changed.json()["name"] == "Contour files"
    assert changed.json()["holder"] == "selection"  # left alone
    assert gone.status_code == 204
    assert client.get("/api/schemas/encounter/exports").json() == []


def test_a_patch_can_clear_the_kind_and_the_filter_by_sending_null(
    client, tree
) -> None:
    good = {"field": "sname", "op": "eq", "value": "s1"}
    client.post("/api/schemas/encounter/exports", json={**BODY, "filter_tree": good})

    cleared = client.patch(
        "/api/schemas/encounter/exports/Contours",
        json={"filter_tree": None, "holder": None, "fields": []},
    )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["filter_tree"] is None
    assert cleared.json()["holder"] is None and cleared.json()["fields"] == []


def test_refusals_say_why(client, tree) -> None:
    client.post("/api/schemas/encounter/exports", json=BODY)

    duplicate = client.post("/api/schemas/encounter/exports", json=BODY)
    above = client.post(
        "/api/schemas/recording/exports", json={"name": "x", "holder": "encounter"}
    )
    bad_field = client.post(
        "/api/schemas/encounter/exports",
        json={"name": "y", "holder": "selection", "fields": ["sname"]},
    )
    bad_layout = client.post(
        "/api/schemas/encounter/exports", json={"name": "z", "files_layout": "spiral"}
    )
    no_schema = client.get("/api/schemas/nope/exports")
    no_export = client.get("/api/schemas/encounter/exports/nope")
    patch_missing = client.patch("/api/schemas/encounter/exports/nope", json={})
    delete_missing = client.delete("/api/schemas/encounter/exports/nope")

    assert duplicate.status_code == 409
    assert above.status_code == 422 and "beneath it" in above.text
    assert bad_field.status_code == 422 and "isn't a file field" in bad_field.text
    assert bad_layout.status_code == 422
    assert no_schema.status_code == 404
    assert no_export.status_code == 404
    assert patch_missing.status_code == 404 and delete_missing.status_code == 404


def test_the_exports_offered_on_a_record_and_on_a_collection(client, tree) -> None:
    client.post("/api/schemas/encounter/exports", json=BODY)

    on_encounter = client.get(
        "/api/file-access/definitions", params={"schema": "encounter"}
    )
    on_recording = client.get(
        "/api/file-access/definitions", params={"schema": "recording"}
    )
    in_collection = client.get(
        "/api/file-access/definitions", params={"collection": "hb"}
    )

    for resp in (on_encounter, on_recording, in_collection):
        assert resp.status_code == 200
        assert [d["name"] for d in resp.json()] == ["Contours"]
    everything = client.get("/api/file-access/definitions")  # no place: every export
    assert everything.status_code == 200
    assert [d["name"] for d in everything.json()] == ["Contours"]
    assert (
        client.get(
            "/api/file-access/definitions", params={"schema": "a", "collection": "b"}
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/file-access/definitions", params={"schema": "nope"}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/file-access/definitions", params={"collection": "nope"}
        ).status_code
        == 404
    )


def test_an_export_runs_on_a_collection(client, tree) -> None:
    client.post("/api/schemas/encounter/exports", json=BODY)

    plan = client.post(
        "/api/file-access/plan",
        json={"export": "encounter/Contours", "collection": "hb"},
    )

    assert plan.status_code == 200, plan.text
    assert [i["path"] for i in plan.json()["items"]] == ["s1.contour", "s2.contour"]


def test_an_export_runs_within_a_record_and_the_layout_can_be_overridden(
    client, tree
) -> None:
    client.post("/api/schemas/encounter/exports", json=BODY)
    within = {"export": "encounter/Contours", "within": str(tree.e7.id)}

    own = client.post("/api/file-access/plan", json=within)
    grouped = client.post("/api/file-access/plan", json={**within, "layout": "grouped"})

    assert [i["path"] for i in own.json()["items"]] == ["s1.contour", "s2.contour"]
    assert [i["path"] for i in grouped.json()["items"]] == [
        "Rec A/Selections/s1.contour",
        "Rec A/Selections/s2.contour",
    ]


def test_an_export_can_be_made_and_zipped_like_any_selection(
    client, tree, project_dir
) -> None:
    client.post("/api/schemas/encounter/exports", json=BODY)
    run = {"export": "encounter/Contours", "collection": "hb"}

    made = client.post(
        "/api/file-access/export", json={**run, "name": "from-def", "mode": "copy"}
    )
    zipped = client.post("/api/file-access/zip", json=run)

    assert made.status_code == 200, made.text
    assert (project_dir / "_civex" / "exports" / "from-def" / "s1.contour").exists()
    assert zipped.status_code == 200


def test_a_bad_export_reference_is_refused_clearly(client, tree) -> None:
    unknown = client.post("/api/file-access/plan", json={"export": "encounter/nope"})
    malformed = client.post("/api/file-access/plan", json={"export": "encounter"})

    assert unknown.status_code == 404
    assert malformed.status_code == 422


def test_an_export_can_carry_a_table_and_drop_the_files(client, tree) -> None:
    body = {
        "name": "Tables",
        "holder": "selection",
        "include_files": False,
        "tables": [{"format": "xlsx", "columns": ["sname"]}],
    }

    made = client.post("/api/schemas/encounter/exports", json=body)

    assert made.status_code == 201, made.text
    assert made.json()["include_files"] is False
    (table,) = made.json()["tables"]
    assert (table["format"], table["columns"], table["kind"], table["where"]) == (
        "xlsx",
        ["sname"],
        None,
        None,
    )

    cleared = client.patch(
        "/api/schemas/encounter/exports/Tables",
        json={"tables": [], "include_files": True, "fields": ["contour"]},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["tables"] == []


def test_an_export_with_neither_files_nor_a_table_is_refused(client, tree) -> None:
    resp = client.post(
        "/api/schemas/encounter/exports",
        json={"name": "Nothing", "holder": "selection", "include_files": False},
    )

    assert resp.status_code == 422


def test_a_saved_export_keeps_tables_that_say_what_they_hold_and_where(
    client, tree
) -> None:
    body = {
        "name": "Sheets",
        "holder": "selection",
        "tables": [
            {
                "format": "csv",
                "columns": ["sname"],
                "kind": "selection",
                "where": "selection",
                "shape": "fields",
                "name": "{sname} metadata",
            }
        ],
    }

    made = client.post("/api/schemas/encounter/exports", json=body)

    assert made.status_code == 201, made.text
    (table,) = made.json()["tables"]
    assert (table["kind"], table["where"], table["shape"], table["name"]) == (
        "selection",
        "selection",
        "fields",
        "{sname} metadata",
    )
    again = client.get("/api/schemas/encounter/exports/Sheets").json()
    assert again["tables"] == made.json()["tables"]


def test_a_saved_table_that_does_not_fit_the_tree_is_refused(client, tree) -> None:
    resp = client.post(
        "/api/schemas/encounter/exports",
        json={
            "name": "Bad",
            "holder": "selection",
            "tables": [{"kind": "nonsense", "where": "nonsense"}],
        },
    )

    assert resp.status_code == 422
