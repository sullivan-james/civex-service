"""`civex clone <repo-url> --release NAME`, end to end: a host serving a release
over a socket, the real command downloading its bundle (files included) and
reading it into a new project that follows nothing and starts read-only."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.config import load_config_at
from civex.context import build_local_context
from civex.domain.exceptions import NotAllowedError
from civex.domain.features import LOCAL_FEATURES, RELEASES
from civex.main import app as cli
from civex.project import Project
from civex.server.app import create_app
from civex.testing import serve
from civex.testing.peers import build_study

runner = CliRunner()


@pytest.fixture()
def host(project, tmp_path: Path) -> Iterator[tuple[str, object, str]]:
    """A host offering releases, serving a project that holds release `v1`
    (records, and a file its records cite)."""
    authority = project("authority")
    build_study(authority)
    authority.schema_svc.add_field("encounter", "photo", "file")
    photo = authority.file_svc.store_bytes(b"a seal", "seal.jpg")
    authority.record_svc.add(
        "study", "encounter", {"site": "z", "photo": photo.to_dict()}
    )
    authority.release_svc.create("v1", "Seal survey", authors=[{"name": "Ada"}])
    authority.commit()
    root = tmp_path / "authority"
    features = LOCAL_FEATURES | {RELEASES}
    web = create_app(features=features)
    web.state.project_resolver = lambda request: dataclasses.replace(
        Project.local(load_config_at(root)), features=features
    )
    previous = os.getcwd()
    try:
        with serve(web) as url:
            yield url, authority, photo.sha256
    finally:
        os.chdir(previous)


def test_a_release_is_cloned_into_a_new_read_only_project(
    host, tmp_path: Path, monkeypatch
):
    url, authority, photo = host
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "copy"
    done = runner.invoke(cli, ["clone", url, str(target), "--release", "v1"])
    assert done.exit_code == 0, done.output
    assert "read-only" in done.output

    copy = build_local_context(load_config_at(target))
    try:
        sample = copy.record_svc.find("study", "encounter", filters=["site=z"])
        assert len(sample) == 1
        # The file came with the bundle, from the host's own files.
        assert copy.file_svc.exists(photo)
        # Nothing is followed and nothing was made a device.
        assert copy.sync_svc.status().remote is None
        # Read-only by default: the copy may be read and cited, not changed.
        with pytest.raises(NotAllowedError):
            copy.record_svc.add("study", "encounter", {"site": "new"})
        # What the authority holds was not touched.
        assert len(authority.release_svc.list_all()) == 1
    finally:
        copy.close()
    assert "read_only = true" in (target / "_civex" / "config.toml").read_text()


def test_a_writable_clone_may_be_changed(host, tmp_path: Path, monkeypatch):
    url, _, _ = host
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "copy"
    done = runner.invoke(
        cli, ["clone", url, str(target), "--release", "v1", "--writable"]
    )
    assert done.exit_code == 0, done.output
    copy = build_local_context(load_config_at(target))
    try:
        copy.record_svc.add("study", "encounter", {"site": "new"})
    finally:
        copy.close()


def test_a_release_that_is_not_there_is_a_clear_refusal_and_leaves_nothing(
    host, tmp_path: Path, monkeypatch
):
    url, _, _ = host
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "copy"
    done = runner.invoke(cli, ["clone", url, str(target), "--release", "v9"])
    assert done.exit_code == 1
    assert "v9" in done.output
    assert not (target / "_civex").exists()


def test_a_plain_http_address_that_is_not_this_computer_is_refused(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    done = runner.invoke(
        cli, ["clone", "http://example.org/o/r/data", "--release", "v1"]
    )
    assert done.exit_code == 1
    assert "https://" in done.output
