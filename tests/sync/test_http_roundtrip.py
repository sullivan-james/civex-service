"""The real client against the real server over a socket: what the Loopback
tests can't show (headers, status mapping, file upload and download)."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from civex.config import load_config, save_config
from civex.domain.sync import SyncError

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
    _, token = authority.authority_svc.add_device("laptop")
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
        yield f"http://127.0.0.1:{port}", token, authority
    finally:
        uv.should_exit = True
        thread.join(timeout=5)
        os.chdir(previous)


def test_a_project_seeds_the_authority_and_a_second_device_joins(project, server):
    url, token, authority = server
    first = project("first")
    populate(first)
    assert first.sync_svc.connect(url, token) == "seeded"
    first.commit()
    assert len(snapshots(authority)["record"]) == 4

    _, token2 = authority.authority_svc.add_device("tablet")
    authority.commit()
    second = project("second")
    assert second.sync_svc.connect(url, token2) == "joined"
    second.commit()
    assert snapshots(second)["record"] == snapshots(authority)["record"]


def test_a_wrong_token_is_a_clear_refusal(project, server):
    url, _, _ = server
    ctx = project("stranger")
    with pytest.raises(SyncError) as e:
        ctx.sync_svc.connect(url, "not-a-token")
    assert not e.value.retryable


def test_an_unreachable_authority_is_retryable(project):
    ctx = project("lonely")
    with pytest.raises(SyncError) as e:
        ctx.sync_svc.connect("http://127.0.0.1:9", "x")
    assert e.value.retryable
