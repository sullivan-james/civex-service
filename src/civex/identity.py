"""Who is making a change on this machine.

History records an author with every entry, and an entry that did not record
one at the time can never be given one later. Until a project syncs, the only
thing civex can honestly say is which operating-system user was running it, so
that is what is recorded. It is informational, set by the machine itself and
not verified: when sync arrives the authority attributes a change from the
caller it authenticated, never from what a client reports.
"""

from __future__ import annotations

import getpass

# audit_log.actor is String(100).
_MAX_LEN = 100


def local_actor() -> str | None:
    """The OS user running civex, or None where there isn't one (some
    containers run as a uid with no name)."""
    try:
        name = getpass.getuser().strip()
    except (KeyError, OSError, ImportError):
        return None
    return name[:_MAX_LEN] or None
