"""Declaration surface shared by every plugin tier.

`id`/`name`/`category`/`capabilities`/`Config` mean the same thing whether a
plugin ends up executing out-of-process (this package's `Plugin`, tier
SUBPROCESS/CONTAINER) or in-process (civex-service's own `Tier0Plugin`,
tier BUILTIN) -- so they're declared exactly once here, instead of on two
independently-maintained classes that could quietly drift apart.

What's tier-specific is only the shape of `ctx` that `invoke()` receives
(the out-of-process `Ctx` deliberately exposes *less* than civex-service's
in-process `WorkflowContext` -- no ambient `.record`/`.dataset`, only what a
plugin explicitly asked for) -- so `invoke()` itself is declared separately
by each tier's own subclass, not here.

This module has no dependency beyond pydantic, so importing it (e.g. from
civex-service) doesn't pull in the RPC/subprocess machinery in ctx.py,
io.py, or serve.py.
"""

from __future__ import annotations

from pydantic import BaseModel


class PluginBase:
    id: str
    name: str
    category: str = "general"
    # Subset of civex_plugin_sdk.protocol.CAPABILITIES this plugin actually
    # calls on ctx.
    capabilities: list[str] = []

    class Config(BaseModel):
        pass
