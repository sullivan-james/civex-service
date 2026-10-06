"""Several civex projects in one test: an authority and the devices that follow it."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.project import scaffold_project

from .peers import build_study, connect, device


@pytest.fixture(autouse=True)
def _user_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Device ids and tokens go to a file of this test's own."""
    monkeypatch.setenv("CIVEX_USER_STATE", str(tmp_path / "user-state.toml"))


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Callable[[str], AppContext]]:
    """project("laptop") -> a context on a new, empty project of that name."""
    made: list[AppContext] = []

    def _make(name: str) -> AppContext:
        root = tmp_path / name
        scaffold_project(root, db_url=f"sqlite:///{(root / 'civex.db').as_posix()}")
        previous = os.getcwd()
        os.chdir(root)
        try:
            config = load_config()
        finally:
            os.chdir(previous)
        ctx = build_local_context(config)
        made.append(ctx)
        return ctx

    yield _make
    for ctx in made:
        ctx.close()


@pytest.fixture()
def authority(project):
    return project("authority")


@pytest.fixture()
def pair(project, authority):
    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    return laptop, phone, record
