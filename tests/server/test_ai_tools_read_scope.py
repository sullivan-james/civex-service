"""The AI assistant reads through the same services as everyone, so a collection
the caller cannot read is not in anything its tools return."""

from __future__ import annotations

import json

from civex.context import build_context
from civex.domain import permissions as p
from civex.services.ai.service import _registry_dispatch
from civex.services.ai.tools.base import AiToolContext

from .test_hidden_collections import SECRET, outsider_perms, world  # noqa: F401


def _tool_ctx(ctx) -> AiToolContext:
    return AiToolContext(
        schema_svc=ctx.schema_svc,
        dataset_svc=ctx.dataset_svc,
        record_svc=ctx.record_svc,
        job_svc=ctx.job_svc,
        workflow_svc=ctx.workflow_svc,
        plugin_svc=ctx.plugin_svc,
        _app_ctx=ctx,
    )


def test_ai_read_tools_leave_a_hidden_collection_out(world):
    ctx = build_context(world.project(outsider_perms(world, p.WRITE_RECORDS)))
    try:
        tools = _tool_ctx(ctx)
        for name, args in (
            ("list_collections", {}),
            ("list_records", {"schema_name": "sample"}),
            ("query_records", {"schema_name": "sample"}),
            ("summarise_records", {"schema_name": "sample"}),
        ):
            out = _registry_dispatch(name, args, tools)
            assert SECRET not in out and SECRET.lower() not in out, name
        listed = json.loads(_registry_dispatch("list_collections", {}, tools))
        assert "topsecret-vault" not in json.dumps(listed)
    finally:
        ctx.close()
