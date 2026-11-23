"""Until sync is limited to what a device may read (C3b), a caller who may not
read the whole project gets none of it: the stack is safe at every commit."""

from __future__ import annotations

import pytest

from civex.config import load_config, save_config
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from tests.server.test_hidden_collections import (  # noqa: F401
    World,
    _client,
    outsider_perms,
    world,
)


def test_sync_is_refused_to_a_caller_who_cannot_read_everything(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(world.root)
    config = load_config()
    config.sync.serve = True
    save_config(config)
    restricted = _client(world, outsider_perms(world, p.WRITE_RECORDS))
    whole = _client(world, Permissions.everything())
    for method, url in (
        ("GET", "/api/sync/v1/feed"),
        ("GET", "/api/sync/v1/hello"),
        ("GET", "/api/sync/v1/snapshot/record"),
        ("POST", "/api/sync/v1/push"),
        ("POST", "/api/sync/v1/files/missing"),
    ):
        r = restricted.request(method, url)
        assert r.status_code == 403, (url, r.status_code)
        assert whole.request(method, url).status_code != 403
