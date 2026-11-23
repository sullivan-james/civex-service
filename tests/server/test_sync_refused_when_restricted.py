"""A device whose person may not read the whole project is served on sync
protocol 5 and up (the feed says how far it looked, the hello lists what it may
read): an older device is told to update, with a clear message, rather than being
served a feed it would read in full at every sync."""

from __future__ import annotations

import pytest

from civex.config import load_config, save_config
from civex.domain import permissions as p
from civex.domain.permissions import Permissions

from .test_hidden_collections import (  # noqa: F401
    World,
    _client,
    outsider_perms,
    world,
)


@pytest.fixture()
def serving(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.chdir(world.root)
    config = load_config()
    config.sync.serve = True
    save_config(config)
    return world


def _get(client, url: str, protocol: str):
    return client.get(url, headers={"x-civex-protocol": protocol})


def test_a_restricted_device_on_protocol_4_is_told_to_update(serving: World):
    restricted = _client(serving, outsider_perms(serving, p.WRITE_RECORDS))
    for url in ("/api/sync/v1/feed", "/api/sync/v1/hello"):
        r = _get(restricted, url, "4")
        assert r.status_code == 426, url
        assert "update" in r.json()["detail"]["message"].lower()
        assert r.json()["detail"]["protocol_min"] == 5


def test_a_restricted_device_on_protocol_5_is_served(serving: World):
    restricted = _client(serving, outsider_perms(serving, p.WRITE_RECORDS))
    r = _get(restricted, "/api/sync/v1/feed", "5")
    assert r.status_code == 401  # past the protocol: it only lacks a token


def test_a_device_that_may_read_everything_is_served_on_protocol_4(serving: World):
    whole = _client(serving, Permissions.everything())
    r = _get(whole, "/api/sync/v1/feed", "4")
    assert r.status_code == 401
