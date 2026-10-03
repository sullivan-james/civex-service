"""Finding blob references inside arbitrary JSON."""

from __future__ import annotations

import re
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def collect_sha256_refs(value: Any, out: set[str] | None = None) -> set[str]:
    """Recursively find every `{"sha256": ...}` dict nested anywhere in
    `value` -- covers `file` fields (a single FileRef dict), `file_list`
    fields (a list of them), and workflow `input_data` (FileRef dicts nested
    under arbitrary input names), all without needing schema field-type
    lookups to know where to look. Only well-formed digests are returned:
    they're stored in a String(64) column and compared against on-disk
    object names."""
    if out is None:
        out = set()
    if isinstance(value, dict):
        sha = value.get("sha256")
        if isinstance(sha, str) and _SHA256_RE.match(sha):
            out.add(sha)
        for v in value.values():
            collect_sha256_refs(v, out)
    elif isinstance(value, list):
        for v in value:
            collect_sha256_refs(v, out)
    return out


def without_file_locations(value: Any) -> Any:
    """`value` with the response-only `location` removed from every file
    reference in it (a `file` value, a `file_list`, or any structure holding
    them). `location` says where a file is *right now*: useful in a response,
    but not something a workflow should see, carry into its outputs, or have
    saved in a job's log."""
    if isinstance(value, dict):
        return {
            k: without_file_locations(v)
            for k, v in value.items()
            if not (k == "location" and "sha256" in value)
        }
    if isinstance(value, list):
        return [without_file_locations(v) for v in value]
    return value
