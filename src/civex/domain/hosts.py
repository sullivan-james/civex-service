"""Whether a host name or address is this machine."""

from __future__ import annotations

import ipaddress


def is_loopback(host: str) -> bool:
    """True for `localhost` and loopback addresses (127.0.0.0/8, ::1)."""
    host = host.strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
