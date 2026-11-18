"""A project is a server for devices or follows one, never both: such a project
sent its records up but never its files (only a follower sends files), and what
its own devices changed reached nobody else. Refused when connecting and when
serving is turned on; a project already set up both ways says so on every
sync instead of half working."""

from __future__ import annotations

import pytest

from civex.domain.exceptions import ValidationError
from civex.domain.sync import SyncError


def test_a_project_that_follows_a_server_cannot_serve_devices(pair):
    laptop, _, _ = pair
    with pytest.raises(ValidationError, match="can't be a server"):
        laptop.sync_svc.set_serving(True)
    assert laptop.project.config.sync.serve is False


def test_a_server_cannot_connect_to_another_server(authority):
    authority.sync_svc.set_serving(True)
    with pytest.raises(SyncError, match="can't follow another server") as e:
        authority.sync_svc.check_connect("https://other.test", "civex_inv_x")
    assert not e.value.retryable
    with pytest.raises(SyncError, match="can't follow another server"):
        authority.sync_svc.request_login("https://other.test")
    assert authority.project.config.sync.remote is None


def test_a_project_set_up_both_ways_says_so_when_it_syncs(pair):
    laptop, _, _ = pair
    laptop.project.config.sync.serve = True  # as a hand edit, or an older civex
    with pytest.raises(SyncError, match="one or the other") as e:
        laptop.sync_svc.sync()
    assert not e.value.retryable
    assert "one or the other" in (laptop.sync_svc.status().last_error or "")

    laptop.sync_svc.set_serving(False)  # turning serving off is always allowed
    laptop.sync_svc.sync()
