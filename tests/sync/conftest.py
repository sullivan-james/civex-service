"""Several civex projects in one test: an authority and the devices that follow
it, with the shipped harness (`civex.testing`)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from civex.testing import Projects, build_study, connect, device


@pytest.fixture(autouse=True)
def _user_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Device ids and tokens go to a file of this test's own."""
    monkeypatch.setenv("CIVEX_USER_STATE", str(tmp_path / "user-state.toml"))


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Projects]:
    """project("laptop") -> a context on a new, empty project of that name."""
    projects = Projects(tmp_path)
    yield projects
    projects.close()


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
