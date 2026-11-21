"""A kind's charts and the Analytics page travel between devices: the
scenarios of `civex.testing.charts`, run against projects in folders."""

from __future__ import annotations

from civex.domain.sync import entry_for, kinds_for, snapshot_for

from civex.testing import charts
from civex.testing.peers import build_study


def test_charts_and_the_page_travel(project, authority):
    assert charts.travels(project, authority) == []


def test_two_first_edits_of_the_page_settle_on_the_authoritys(project, authority):
    assert charts.two_first_edits(project, authority) == []


def test_a_device_on_the_previous_protocol_gets_what_it_can_read(project):
    ctx = project("p")
    build_study(ctx)
    ctx.schema_svc.set_charts("encounter", [{"id": "a", "group_by": ["site"]}])
    ctx.schema_svc.set_charts("encounter", [{"id": "a", "group_by": ["depth:5"]}])
    ctx.dashboard_svc.add(chart={"group_by": ["site"]}, schema="encounter")
    ctx.commit()
    entries = [e.on_the_wire() for e in ctx.sync_repo.pending_entries(100)]
    old = [e for entry in entries if (e := entry_for(3, entry)) is not None]

    assert "dashboard" not in kinds_for(3)
    assert {e.entity_type for e in old} == {"schema", "field", "dataset", "record"}
    for e in old:
        for side in (e.old_data, e.new_data):
            assert "charts" not in (side or {})
        assert not any(p.startswith("charts") for p in e.delta or {})
    (snap,) = ctx.sync_repo.snapshots_page("schema", None, 10)
    assert "charts" in snap and "charts" not in snapshot_for(3, "schema", snap)
    # And on the current protocol, nothing is cut.
    assert [entry_for(4, e) for e in entries] == entries
