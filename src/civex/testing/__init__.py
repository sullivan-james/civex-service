"""The sync test harness, shipped: what proves an authority correct.

`tests/sync` plays devices against an authority with these helpers; a host that
embeds civex (a hosted service serving many projects) runs the same scenarios
with **its** app as the authority, so parity is a test and not a promise.

- `Projects(root)`: `project("laptop")` makes a new, empty project under `root`
  and returns a context on it; `close()` closes them all.
- `peers`: `device(project, authority, name)` is a project that syncs to
  `authority` over an in-process loopback (`Loopback`, the real JSON both
  ways; `Flaky` drops replies on purpose); `connect`, `follow`, `push`,
  `snapshots`, `build_study`. The authority is any `AppContext`: one built
  with `build_local_context`, or one a host built its own way (its project
  resolver, authenticator, permissions and store).
- `convergence.scenario` and `invariants.scenario`: three flaky devices make
  random changes and sync at random; afterwards every copy must agree and
  must still be a project one machine could hold. Each returns the problems
  found (none is a pass), and a seed replays a failure.
- `serve(app)`: the app under uvicorn on a free loopback port, for the real
  HTTP transport.
- `fake_s3.FakeS3`: a bucket in memory, shaped like a boto3 client, with an
  HTTP front for the presigned URLs it hands out.

Nothing here imports pytest: wrap these in whatever fixtures the suite uses.
Set `CIVEX_USER_STATE` to a file of the test's own, since device ids and keys
are kept per user, not per project.
"""

from civex.testing.peers import (
    AsDevice,
    Flaky,
    Loopback,
    build_study,
    by_status,
    connect,
    device,
    device_uuid,
    flaky,
    follow,
    join,
    new_id,
    principal,
    push,
    snapshots,
    statuses,
    wire,
)
from civex.testing.projects import Projects
from civex.testing.server import serve

__all__ = [
    "AsDevice",
    "Flaky",
    "Loopback",
    "Projects",
    "build_study",
    "by_status",
    "connect",
    "device",
    "device_uuid",
    "flaky",
    "follow",
    "join",
    "new_id",
    "principal",
    "push",
    "serve",
    "snapshots",
    "statuses",
    "wire",
]
