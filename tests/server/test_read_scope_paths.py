"""The read rule holds for the paths a query does not make itself: an object
already in the session's identity map after unscoped work, and a relationship
loaded lazily from a visible object."""

from __future__ import annotations

from civex.context import build_context
from civex.db import read_scope
from civex.db.models import Dataset, Record
from civex.domain import permissions as p

from .test_hidden_collections import outsider_perms, world  # noqa: F401


def test_identity_map_and_lazy_loads_do_not_reach_hidden_rows(world):
    ctx = build_context(world.project(outsider_perms(world, p.WRITE_RECORDS)))
    s = ctx._session
    hidden = world.hidden[0].id
    with read_scope.unscoped(s):
        assert s.get(Record, hidden) is not None  # now in the identity map
    assert s.get(Record, hidden) is None
    s.expire_all()
    assert s.get(Record, hidden) is None
    visible = {str(r.id) for r in world.visible}
    dataset = s.query(Dataset).filter_by(name="open").one()
    assert {str(r.id) for r in dataset.records} == visible
    assert s.query(Dataset).filter_by(name="topsecret-vault").first() is None
    ctx.close()
