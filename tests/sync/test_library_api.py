"""The library over HTTP: the authority's peer routes, and the app's own."""

from __future__ import annotations

import hashlib

import pytest

from civex.config import load_config, save_config
from civex.domain.sync import protocol_header

_WORKFLOW = "name: tidy\nsteps:\n  - id: a\n    plugin: civex.get_field\n    config:\n      field: site\n"


def _item(kind="workflow", name="tidy", content=_WORKFLOW, **extra):
    return {
        "kind": kind,
        "name": name,
        "content": content,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "size": len(content.encode()),
        **extra,
    }


@pytest.fixture()
def serving(ctx, client, sign_in_over_http):
    config = load_config()
    config.sync.serve = True
    save_config(config)
    _, invite = ctx.device_keys.invite("laptop")
    ctx.commit()
    headers = {
        "Authorization": f"Bearer {sign_in_over_http(client, invite)}",
        "X-Civex-Protocol": protocol_header(),
    }
    return client, headers


def test_a_device_reads_the_library_and_publishes_only_when_allowed(serving, ctx):
    client, headers = serving
    assert client.get("/api/sync/v1/library", headers=headers).json() == {"items": []}

    refused = client.post(
        "/api/sync/v1/library", json={"items": [_item()]}, headers=headers
    )
    assert refused.status_code == 403
    assert "may not publish" in refused.json()["detail"]

    ctx.device_keys.allow_publish("laptop", True)
    ctx.commit()
    taken = client.post("/api/sync/v1/library", json={"items": [_item()]}, headers=headers)
    assert taken.status_code == 200
    [listed] = taken.json()["items"]
    assert listed["published_by"] == "laptop" and "content" not in listed

    one = client.get("/api/sync/v1/library/workflow/tidy", headers=headers).json()
    assert one["content"] == _WORKFLOW
    assert client.get(
        "/api/sync/v1/library/workflow/nope", headers=headers
    ).status_code == 404

    # Plugins are code: not taken until the admin says so.
    plugin = _item("plugin", "step", "class Plugin:\n    pass\n", provides="project.step")
    reply = client.post("/api/sync/v1/library", json={"items": [plugin]}, headers=headers)
    assert reply.status_code == 403

    damaged = _item() | {"sha256": "0" * 64}
    reply = client.post("/api/sync/v1/library", json={"items": [damaged]}, headers=headers)
    assert reply.status_code == 422

    assert client.delete(
        "/api/sync/v1/library/workflow/tidy", headers=headers
    ).status_code == 204


def test_the_library_needs_a_signed_in_device_on_a_serving_server(client, serving):
    _, headers = serving
    unsigned = {"X-Civex-Protocol": protocol_header()}
    assert client.get("/api/sync/v1/library", headers=unsigned).status_code == 401
    config = load_config()
    config.sync.serve = False
    save_config(config)
    assert client.get("/api/sync/v1/library", headers=headers).status_code == 404


def test_the_authority_admin_sets_what_the_library_takes_and_who_publishes(
    serving, client
):
    reply = client.patch("/api/remote/authority", json={"library": "all"})
    assert reply.status_code == 200 and reply.json()["library"] == "all"
    assert load_config().sync.library == "all"
    assert client.patch("/api/remote/authority", json={"library": "lots"}).status_code == 422

    reply = client.post(
        "/api/remote/authority/devices/laptop/publish", json={"allowed": True}
    )
    [laptop] = reply.json()["devices"]
    assert laptop["may_publish"] is True


def test_the_authority_publishes_and_installs_through_the_app(serving, client, ctx):
    ctx.workflow_svc.save("tidy", _WORKFLOW)
    reply = client.post(
        "/api/remote/library/publish", json={"kind": "workflow", "name": "tidy"}
    )
    assert reply.status_code == 200, reply.text
    [listed] = client.get("/api/remote/library").json()
    assert listed["here"] == "same" and listed["filename"] == "tidy.yaml"

    plan = client.get("/api/remote/library/workflow/tidy/install").json()
    assert plan["blocked"] == [] and plan["runs_code"] is False
