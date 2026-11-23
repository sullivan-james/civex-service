"""`Project.push_accepted`: a host is told, once, after a device's push has
been committed and took something -- who sent it and what went in -- so it
needs no middleware reading its responses."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from civex.config import load_config, save_config
from civex.domain.sync import PushAccepted
from civex.project import Project
from civex.testing import serve
from civex.testing.convergence import populate


@contextlib.contextmanager
def _host(project, tmp_path: Path, callback) -> Iterator[tuple[str, str]]:
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

    app = create_app()
    app.state.project_resolver = lambda request: replace(
        Project.local(load_config()), actor="hub user", push_accepted=callback
    )
    try:
        with serve(app) as url:
            yield url, invite
    finally:
        os.chdir(previous)


@pytest.fixture()
def told() -> list[PushAccepted]:
    return []


@pytest.fixture()
def hosted(project, tmp_path: Path, told):
    with _host(project, tmp_path, told.append) as (url, invite):
        yield url, invite


def test_the_host_is_told_once_per_push_that_took_something(project, hosted, told):
    url, invite = hosted
    laptop = project("laptop")
    populate(laptop)
    laptop.sync_svc.connect(url, invite)
    laptop.commit()
    seeded = list(told)
    assert seeded, "the first push (the seed) took changes"
    told.clear()

    laptop.record_svc.add("study", "encounter", {"site": "new", "depth": 9.0})
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.commit()
    assert len(told) == 1
    report = told[0]
    assert report.device == "laptop"
    assert report.actor == "hub user"
    assert report.changed.get("record") == 1
    assert len(report.taken) == 1 and report.counts.get("applied") == 1
    assert report.first_seq is not None and report.first_seq <= report.last_seq

    told.clear()
    laptop.sync_svc.sync()  # nothing new to send
    laptop.commit()
    assert told == []  # a push that took nothing is not announced


def test_a_failing_callback_never_fails_the_push(project, tmp_path: Path):
    def broken(report):
        raise RuntimeError("the host's bookkeeping is down")

    with _host(project, tmp_path, broken) as (url, invite):
        laptop = project("laptop")
        populate(laptop)
        assert laptop.sync_svc.connect(url, invite) == "seeded"
        laptop.commit()
        laptop.record_svc.add("study", "encounter", {"site": "more", "depth": 2.0})
        laptop.commit()
        laptop.sync_svc.sync()
        laptop.commit()
        assert not laptop.sync_repo.pending_entries(10)  # it all went in
