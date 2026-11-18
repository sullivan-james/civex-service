"""Trying a workflow on a record keeps nothing, and says what it would do;
a workflow switched off starts no runs by itself."""

from __future__ import annotations

from fastapi.testclient import TestClient

_COPY = """\
name: copy-subject
record_schema: doc
triggers:
  record_updated:
    schema: doc
    fields: [subject]
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: subject
  - id: save
    plugin: civex.save_field
    config:
      field: title
    inputs:
      value: read.value
"""


def _record(client: TestClient, **data) -> str:
    client.post("/api/schemas", json={"name": "doc", "description": None})
    for name in ("subject", "title"):
        client.post(
            "/api/schemas/doc/fields",
            json={"name": name, "type": "string", "required": False},
        )
    client.post("/api/collections", json={"name": "study", "description": None})
    resp = client.post(
        "/api/collections/study/records",
        json={"schema_name": "doc", "data": data},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _jobs(client: TestClient) -> list[dict]:
    return client.get("/api/jobs").json()


def test_a_trial_says_what_would_change_and_keeps_nothing(client: TestClient) -> None:
    rid = _record(client, subject="Whale song", title="old")
    resp = client.post("/api/workflows/try", json={"content": _COPY, "record_id": rid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert [s["status"] for s in body["steps"]] == ["success", "success"]
    [change] = body["changes"]
    assert change["action"] == "updated"
    assert change["record_id"] == rid
    assert [(f["field"], f["before"], f["after"]) for f in change["fields"]] == [
        ("title", "old", "Whale song")
    ]
    # Nothing stayed: not the value, and not a run.
    record = client.get(f"/api/records/{rid}").json()
    assert record["data"]["title"] == "old"
    assert _jobs(client) == []


def test_a_trial_names_the_runs_its_saves_would_start(client: TestClient) -> None:
    rid = _record(client, subject="a", title="b")
    client.put("/api/workflows/copy-subject", json={"content": _COPY})
    # A workflow that saves the field copy-subject watches.
    setter = """\
name: set-subject
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: title
  - id: save
    plugin: civex.save_field
    config:
      field: subject
    inputs:
      value: read.value
"""
    resp = client.post("/api/workflows/try", json={"content": setter, "record_id": rid})
    assert resp.status_code == 200, resp.text
    assert resp.json()["would_start"] == {"copy-subject": 1}
    assert _jobs(client) == []


def test_a_failing_step_is_reported_not_raised(client: TestClient) -> None:
    rid = _record(client, subject="a")
    broken = _COPY.replace("civex.get_field", "civex.extract_from_filename").replace(
        "field: subject\n  - id: save", "field: nope\n  - id: save"
    )
    resp = client.post("/api/workflows/try", json={"content": broken, "record_id": rid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["step"] == "read"
    assert body["changes"] == []


def test_a_trial_refuses_a_record_of_another_kind(client: TestClient) -> None:
    rid = _record(client, subject="a")
    other = _COPY.replace("record_schema: doc", "record_schema: sample")
    resp = client.post("/api/workflows/try", json={"content": other, "record_id": rid})
    assert resp.status_code == 422
    assert "sample" in resp.json()["detail"]


def test_a_trial_checks_the_yaml_like_a_save(client: TestClient) -> None:
    rid = _record(client)
    resp = client.post(
        "/api/workflows/try",
        json={
            "content": _COPY.replace("civex.get_field", "civex.nope"),
            "record_id": rid,
        },
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


def test_switching_off_stops_triggers_but_not_a_manual_run(client: TestClient) -> None:
    rid = _record(client, subject="a")
    commented = "# kept\n" + _COPY
    client.put("/api/workflows/copy-subject", json={"content": commented})

    resp = client.patch("/api/workflows/copy-subject", json={"enabled": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False
    assert resp.json()["content"].startswith("# kept\nenabled: false\nname:")
    assert client.get("/api/workflows").json()[0]["enabled"] is False

    client.patch(f"/api/records/{rid}", json={"data": {"subject": "b"}})
    assert _jobs(client) == []

    run = client.post("/api/workflows/copy-subject/run", json={"record_id": rid})
    assert run.status_code == 202

    resp = client.patch("/api/workflows/copy-subject", json={"enabled": True})
    assert "enabled: true\n" in resp.json()["content"]
    assert resp.json()["content"].count("enabled:") == 1


def test_trying_on_the_latest_records_needs_no_choice_and_keeps_nothing(
    client: TestClient,
) -> None:
    first = _record(client, subject="one", title="x")
    later = []
    for subject in ("two", "three"):
        resp = client.post(
            "/api/collections/study/records",
            json={"schema_name": "doc", "data": {"subject": subject, "title": "x"}},
        )
        later.append(resp.json()["id"])
    # The first record changed last, so it is tried first.
    client.patch(
        f"/api/records/{first}", json={"data": {"subject": "one!", "title": "x"}}
    )

    resp = client.post("/api/workflows/try-many", json={"content": _COPY, "sample": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sampled"] is True
    assert [t["record_id"] for t in body["trials"]] == [first, later[1]]
    afters = [t["result"]["changes"][0]["fields"][0]["after"] for t in body["trials"]]
    assert afters == ["one!", "three"]
    for rid in [first, *later]:
        assert client.get(f"/api/records/{rid}").json()["data"]["title"] == "x"
    assert _jobs(client) == []


def test_trying_on_named_records_says_where_it_cannot_run(client: TestClient) -> None:
    rid = _record(client, subject="a", title="b")
    client.post("/api/schemas", json={"name": "other", "description": None})
    other = client.post(
        "/api/collections/study/records", json={"schema_name": "other", "data": {}}
    ).json()["id"]
    resp = client.post(
        "/api/workflows/try-many",
        json={"content": _COPY, "record_ids": [rid, other, "ffffffff"]},
    )
    assert resp.status_code == 200, resp.text
    trials = resp.json()["trials"]
    assert trials[0]["result"]["ok"] is True
    assert trials[1]["result"] is None and "doc records" in trials[1]["problem"]
    assert trials[2]["problem"] == "No such record."
