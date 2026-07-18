"""Shared helpers for AiTool implementations: JSON error/proposal envelope
builders, and the validate-then-rollback pattern act tools use to check a
proposal against real service validation without persisting it (CIVEX-49).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from civex.domain.exceptions import CivexError
from civex.services.ai.tools.base import AiToolContext


def tool_error(message: str) -> str:
    return json.dumps({"status": "error", "message": message})


def q(v: Any) -> str:
    return quote(str(v), safe="")


def record_or_none(ctx: AiToolContext, rid: str):
    try:
        return ctx.record_svc.get(str(rid))
    except Exception:
        return None


def record_summary(r) -> dict:
    """Compact, file-safe view of a record for tool results (ids + field data)."""
    data: dict[str, Any] = {}
    for k, v in r.data.items():
        if isinstance(v, dict) and "sha256" in v:
            data[k] = f"<file: {v.get('filename', 'unknown')}>"
        elif isinstance(v, list) and v and isinstance(v[0], dict) and "sha256" in v[0]:
            data[k] = [f"<file: {f.get('filename', 'unknown')}>" for f in v]
        else:
            data[k] = v
    return {"id": str(r.id), "schema": r.schema_name, "data": data}


def propose(
    action: str,
    summary: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    destructive: bool = False,
    preview: dict | None = None,
) -> str:
    request: dict[str, Any] = {"method": method, "path": path}
    if body is not None:
        request["body"] = body
    out: dict[str, Any] = {
        "status": "proposed",
        "action": action,
        "summary": summary,
        "destructive": destructive,
        "request": request,
    }
    if preview is not None:
        out["preview"] = preview
    return json.dumps(out)


def validate_via(ctx: AiToolContext, fn, *args, **kwargs) -> str | None:
    """Call a real service method inside ctx.validation_scope() -- a SQL
    SAVEPOINT that's always rolled back on exit, success or failure. Returns
    a tool_error() string on failure, None on success.
    """
    try:
        with ctx.validation_scope():
            fn(*args, **kwargs)
    except (CivexError, ValueError) as e:
        return tool_error(str(e))
    return None
