"""The real client against the real server over a socket: what the Loopback
tests can't show (headers, status mapping, file upload and download)."""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import replace
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from civex import keys
from civex.config import load_config, save_config
from civex.domain.sync import SyncError, session_answer
from civex.services.device_keys import DeviceKeys

from .peers import snapshots
from .test_convergence import populate


@pytest.fixture()
def server(project, tmp_path: Path) -> Iterator[tuple[str, str, object]]:
    authority = project("authority")
    root = tmp_path / "authority"
    previous = os.getcwd()
    os.chdir(root)
    config = load_config()
    config.sync.serve = True
    save_config(config)
    _, invite = authority.device_keys.invite("laptop")
    authority.commit()

    from civex.server.app import create_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    uv = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}", invite, authority
    finally:
        uv.should_exit = True
        thread.join(timeout=5)
        os.chdir(previous)


def test_a_project_seeds_the_authority_and_a_second_device_joins(project, server):
    url, invite, authority = server
    first = project("first")
    populate(first)
    assert first.sync_svc.connect(url, invite) == "seeded"
    first.commit()
    assert len(snapshots(authority)["record"]) == 4

    _, invite2 = authority.device_keys.invite("tablet")
    authority.commit()
    second = project("second")
    assert second.sync_svc.connect(url, invite2) == "joined"
    second.commit()
    assert snapshots(second)["record"] == snapshots(authority)["record"]
    # Joined once, a device signs in with its key from then on.
    second.sync_svc.sync()


def test_a_wrong_invite_is_a_clear_refusal(project, server):
    url, _, _ = server
    ctx = project("stranger")
    with pytest.raises(SyncError, match="invite") as e:
        ctx.sync_svc.connect(url, "civex_inv_not-one")
    assert not e.value.retryable


def test_a_different_server_at_the_address_is_refused_before_anything_is_sent(
    project, server, monkeypatch
):
    """The device keeps the key of the authority it joined; a server that can't
    sign with it (another machine at that address) gets nothing."""
    url, invite, authority = server
    first = project("first")
    populate(first)
    assert first.sync_svc.connect(url, invite) == "seeded"
    first.commit()
    real = DeviceKeys.start_session
    impostor = keys.new_private_key()

    def answer_as_another(self, device_id, at, signature):
        grant = real(self, device_id, at, signature)
        return replace(grant, signature=keys.sign(impostor, session_answer(signature)))

    monkeypatch.setattr(DeviceKeys, "start_session", answer_as_another)
    pushed = len(authority.sync_repo.entries_after(0, 1000)[0])
    first.record_svc.add("study", "encounter", {"site": "new", "depth": 9.0})
    first.commit()
    with pytest.raises(SyncError, match="not the one this computer joined") as e:
        first.sync_svc.sync()
    assert not e.value.retryable
    assert len(authority.sync_repo.entries_after(0, 1000)[0]) == pushed


def test_an_unreachable_authority_is_retryable(project):
    ctx = project("lonely")
    with pytest.raises(SyncError) as e:
        ctx.sync_svc.connect("http://127.0.0.1:9", "civex_inv_x")
    assert e.value.retryable


def test_the_library_over_a_socket(project, server):
    """Versions, a refusal (403, kept apart from a sign-in failure) and a
    removal (204, no body) through the real transport."""
    from civex.domain.exceptions import NotAllowedError
    from civex.domain.library import WORKFLOW

    url, invite, authority = server
    laptop = project("laptop")
    laptop.sync_svc.connect(url, invite)
    laptop.commit()
    text = "name: tidy\nsteps:\n  - id: a\n    plugin: civex.get_field\n    config:\n      field: site\n"
    laptop.workflow_svc.save("tidy", text)

    with pytest.raises(NotAllowedError, match="may not publish"):
        laptop.library_svc.publish(WORKFLOW, "tidy")

    authority.device_keys.allow_publish("laptop", True)
    authority.commit()
    assert laptop.library_svc.publish(WORKFLOW, "tidy").items[0].version == 1
    laptop.workflow_svc.save("tidy", text.replace("site", "depth"))
    assert laptop.library_svc.publish(WORKFLOW, "tidy").items[0].version == 2

    first = laptop.library_svc.show(WORKFLOW, "tidy", version=1)
    assert first.content == text and first.local_version == 2
    laptop.library_svc.unpublish(WORKFLOW, "tidy", version=1)
    [left] = laptop.library_svc.browse()
    assert [h["version"] for h in left.history] == [2]
