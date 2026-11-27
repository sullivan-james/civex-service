"""The pack download route through the real `peer` dependency (a device's
session, its limited permissions), and what the client keeps in hand."""

from __future__ import annotations

import dataclasses
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from tempfile import SpooledTemporaryFile

import pytest
from fastapi.testclient import TestClient

from civex.config import load_config, load_config_at, save_config
from civex.domain import features
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import SyncError, protocol_header
from civex.project import Project
from civex.server.app import create_app
from civex.services import sync_service
from civex.services.sync_transport import PackAnswer

from .test_parallel_downloads import Line, _cite, _phone

URL = "/api/sync/v1/files/pack/download"


def _host(
    project_dir, ctx, sign_in_over_http, perms=None, extra_features=(), name="laptop"
):
    config = load_config()
    config.sync.serve = True
    save_config(config)
    _, invite = ctx.device_keys.invite(name)
    ctx.commit()
    app = create_app()

    def resolve(request):
        project = Project.local(load_config_at(project_dir))
        if perms is not None:
            project = dataclasses.replace(project, permissions=perms)
        if extra_features:
            project = dataclasses.replace(
                project, features=project.features | set(extra_features)
            )
        return project

    app.state.project_resolver = resolve
    client = TestClient(app, raise_server_exceptions=False)
    headers = {
        "Authorization": f"Bearer {sign_in_over_http(client, invite)}",
        "X-Civex-Protocol": protocol_header(),
    }
    return client, headers


def _two_collections(ctx):
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field("encounter", "scan", "file")
    shown = ctx.dataset_svc.create("open")
    hidden = ctx.dataset_svc.create("vault")
    refs = {}
    for name in ("open", "vault"):
        ref = ctx.file_svc.store_bytes(f"{name} bytes".encode(), f"{name}.bin")
        ctx.record_svc.add(name, "encounter", {"scan": ref.to_dict()})
        refs[name] = ref.sha256
    ctx.commit()
    return shown, hidden, refs


def test_a_device_limited_to_a_collection_gets_only_its_files(
    project_dir, ctx, sign_in_over_http
):
    shown, hidden, refs = _two_collections(ctx)
    perms = Permissions.of(
        p.READ, collections=(shown.id,), read_collections=(shown.id,)
    )
    client, headers = _host(project_dir, ctx, sign_in_over_http, perms)
    unknown = "e" * 64
    reply = client.post(
        URL,
        headers=headers,
        json={"sha256": [refs["open"], refs["vault"], unknown]},
    )
    assert reply.status_code == 200
    assert b"vault bytes" not in reply.content
    assert f"{refs['vault']} absent\n".encode() in reply.content
    assert f"{unknown} absent\n".encode() in reply.content  # as if there were none
    assert f"{refs['open']} 10\nopen bytes".encode() in reply.content
    # The same device, whole project: both.
    client, headers = _host(project_dir, ctx, sign_in_over_http, name="full")
    both = client.post(
        URL, headers=headers, json={"sha256": [refs["open"], refs["vault"]]}
    )
    assert b"vault bytes" in both.content


@pytest.mark.parametrize(
    "hashes",
    [["not-a-hash"], ["A" * 64], ["e" * 63], ["e" * 65], ["e" * 64] * 101],
)
def test_a_malformed_ask_is_refused(project_dir, ctx, sign_in_over_http, hashes):
    client, headers = _host(project_dir, ctx, sign_in_over_http)
    assert client.post(URL, headers=headers, json={"sha256": hashes}).status_code == 422


def test_a_host_with_files_in_a_bucket_does_not_serve_packs(
    project_dir, ctx, sign_in_over_http
):
    client, headers = _host(
        project_dir, ctx, sign_in_over_http, extra_features=[features.DIRECT_FILES]
    )
    reply = client.post(URL, headers=headers, json={"sha256": ["e" * 64]})
    assert reply.status_code == 501


# -- what the client keeps in hand ------------------------------------------


class Counting(ThreadPoolExecutor):
    """Counts the requests handed to it and not yet done (running or waiting)."""

    outstanding = 0
    peak = 0
    _count = threading.Lock()

    def submit(self, fn, *args, **kwargs):
        with Counting._count:
            Counting.outstanding += 1
            Counting.peak = max(Counting.peak, Counting.outstanding)
        future = super().submit(fn, *args, **kwargs)

        def done(_):
            with Counting._count:
                Counting.outstanding -= 1

        future.add_done_callback(done)
        return future


class PackLine(Line):
    """Says every file is to be asked for alone (too big for a pack)."""

    download_threads = 2

    def accepts_pack_downloads(self):
        return True

    def fetch_pack(self, shas, stop=None):
        return PackAnswer(spool=SpooledTemporaryFile(), alone=list(shas))

    def fetch_file(self, sha, stop=None):
        time.sleep(0.01)
        try:
            chunks = self.file_chunks(sha)
        except FileNotFoundError:
            return None
        spool = SpooledTemporaryFile()
        for chunk in chunks:
            spool.write(chunk)
        spool.seek(0)
        return spool


def test_files_to_ask_for_alone_stay_within_the_window(pair, monkeypatch):
    monkeypatch.setattr(sync_service, "ThreadPoolExecutor", Counting)
    monkeypatch.setattr(sync_service, "PACK_DOWNLOAD_FILES", 10)
    phone, files, line = _phone(pair, monkeypatch, PackLine)
    Counting.outstanding = Counting.peak = 0
    report = phone.sync_svc.fetch_files()
    phone.commit()
    assert report.fetched == 30
    # Two threads: at most four requests open or waiting, whatever a pack says.
    assert 0 < Counting.peak <= line.download_threads * 2


def test_a_file_with_the_wrong_content_never_deletes_one_the_device_holds(
    pair, monkeypatch
):
    held = pair[1].file_svc.store_bytes(b"already here", "held.bin")
    pair[1].commit()
    seen = {}

    def make(files):
        seen["bad"] = sorted(files)[3]
        return Line({**files, seen["bad"]: b"already here"})

    phone, files, line = _phone(pair, monkeypatch, make)
    with pytest.raises(SyncError, match="wrong content"):
        phone.sync_svc.fetch_files()
    phone.commit()
    assert phone.file_svc.exists(held.sha256)
    assert not phone.file_svc.exists(seen["bad"])
