"""The record API says when a record sits under a deleted one, lists every
such record, and puts one back in place."""

from __future__ import annotations

from sqlalchemy import update

from civex.db.models import Record


def test_orphans_are_listed_shown_and_put_back(
    client, ctx, make_schema, make_collection, make_record
):
    make_schema("recording", fields=[("label", "string")])
    make_schema("selection", fields=[("n", "integer")], parent="recording")
    make_collection("survey")
    rec = make_record("survey", "recording", {"label": "R"})
    sel = make_record("survey", "selection", {"n": 1}, parent_record_id=str(rec.id))
    ctx.record_svc.delete(str(rec.id))
    ctx._session.execute(
        update(Record).where(Record.id == sel.id).values(deleted_at=None)
    )
    ctx.commit()

    listed = client.get("/api/records/orphans").json()
    assert listed["total"] == 1
    assert listed["items"][0]["record"]["id"] == str(sel.id)
    assert [a["id"] for a in listed["items"][0]["above"]] == [str(rec.id)]

    shown = client.get(f"/api/records/{sel.id}").json()
    assert [a["id"] for a in shown["deleted_above"]] == [str(rec.id)]

    put_back = client.post(f"/api/records/{sel.id}/restore-above")
    assert put_back.status_code == 200
    assert [r["id"] for r in put_back.json()] == [str(rec.id)]
    assert client.get("/api/records/orphans").json()["total"] == 0
    assert client.get(f"/api/records/{sel.id}").json()["deleted_above"] == []

    again = client.post(f"/api/records/{sel.id}/restore-above")
    assert again.status_code == 422
