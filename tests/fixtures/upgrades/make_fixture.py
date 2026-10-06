"""Build the upgrade fixture for a release, with that release's own code.

    git worktree add /some/disk/rel v1.2.0 && cd /some/disk/rel && uv sync
    mkdir /some/disk/p && cd /some/disk/p && /some/disk/rel/.venv/bin/civex init
    /some/disk/rel/.venv/bin/python <this file>
    gzip -9 -c _civex/civex.db > tests/fixtures/upgrades/civex-1.2.0.db.gz

Use a folder on disk with its own project (never one under a real project, and
not /tmp here: it is RAM). Steps a release can't do are skipped and said so."""

import inspect

from civex.config import load_config
from civex.context import build_local_context

ctx = build_local_context(load_config())
done = []


def step(name, fn):
    try:
        fn()
        ctx.commit()
        done.append(name)
    except Exception as e:  # noqa: BLE001
        ctx._session.rollback()
        print(f"skipped {name}: {type(e).__name__}: {e}")


step(
    "schemas",
    lambda: (
        ctx.schema_svc.create("site"),
        ctx.schema_svc.add_field("site", "name", "string"),
        ctx.schema_svc.add_field("site", "depth", "float"),
        ctx.schema_svc.add_field("site", "notes", "string"),
        ctx.schema_svc.create("visit", parent="site"),
        ctx.schema_svc.add_field("visit", "when", "string"),
    ),
)
step("collection", lambda: ctx.dataset_svc.create("survey"))
if "schemas" in inspect.signature(ctx.dataset_svc.update).parameters:
    step(
        "schema list",
        lambda: ctx.dataset_svc.update("survey", schemas=["site", "visit"]),
    )

sites = []


def add_records():
    for i in range(20):
        s = ctx.record_svc.add(
            "survey", "site", {"name": f"s{i}", "depth": float(i), "notes": "n" * 300}
        )
        sites.append(s)
        ctx.record_svc.add(
            "survey", "visit", {"when": f"day {i}"}, parent_record_id=str(s.id)
        )


step("records", add_records)


def edit_records():
    for n in range(3):
        for i, s in enumerate(sites):
            ctx.record_svc.update(
                str(s.id),
                {"name": f"s{i}-{n}", "depth": float(i + n), "notes": "n" * 300},
            )


step("edits", edit_records)
step(
    "rename field",
    lambda: ctx.schema_svc.update_field("site", "notes", new_name="remarks"),
)
step("delete", lambda: ctx.record_svc.delete(str(sites[0].id)))
step("restore", lambda: ctx.record_svc.restore(str(sites[0].id)))
step("delete another", lambda: ctx.record_svc.delete(str(sites[1].id)))
ctx.close()
print("done:", ", ".join(done))
