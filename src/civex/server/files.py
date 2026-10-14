"""Headers for handing a file over, shared by the routes that do."""

from __future__ import annotations

import urllib.parse


def attachment(filename: str) -> str:
    """`Content-Disposition: attachment` naming the file both ways a browser
    reads (RFC 6266 and RFC 5987), so any name survives."""
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    encoded = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
