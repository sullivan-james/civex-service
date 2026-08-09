"""Declaration surface shared by every plugin tier.

`id`/`name`/`description`/`category`/`capabilities`/`inputs`/`outputs`/
`Config` mean the same thing whether a plugin ends up executing
out-of-process (this package's `Plugin`, tier SUBPROCESS/CONTAINER) or
in-process (civex-service's own `Tier0Plugin`, tier BUILTIN) -- so they're
declared exactly once here, instead of on two independently-maintained
classes that could quietly drift apart.

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

IO_TYPES = (
    "any",
    "string",
    "number",
    "boolean",
    "bytes",
    "table",
    "files",
    "records",
    "mapping",
    "list",
)
"""Vocabulary for `IOSpec.type`.

Deliberately coarse: a step input/output is a live Python object (a
DataFrame, raw bytes, a list of FileRef dicts), so this names the *shape a
workflow author needs to know when wiring one step into the next*, not a
validatable type. Nothing ever validates a runtime value against it --
host-side contract checking matches input and output *names*, never types.

    any      no constraint / plugin-specific
    string   text scalar
    number   int or float
    boolean  true/false
    bytes    raw binary payload
    table    tabular data (a pandas DataFrame in-process)
    files    list of FileRef dicts ({sha256, filename, size})
    records  list of record dicts
    mapping  dict keyed by field/column name
    list     list of anything not covered by files/records
"""


class IOSpec(BaseModel):
    """One declared input or output of a plugin.

    `type` is a plain `str` rather than a `Literal[IO_TYPES]` on purpose:
    this model crosses the wire in a `describe_result`, and a Literal would
    make an older host *fail discovery entirely* on a plugin built against a
    newer SDK that added a vocabulary entry. An unrecognized type should
    degrade to being displayed as-is, not take the plugin down. In-repo
    declarations are held to the vocabulary by test, where a typo is worth
    failing on.
    """

    name: str
    type: str = "any"
    required: bool = True
    description: str = ""


class PluginBase:
    """Declarative metadata shared by every plugin tier (BUILTIN, SUBPROCESS, CONTAINER).

    Set the class attributes below on a subclass; `invoke()` itself is
    declared separately by each tier (see this package's `Plugin` for the
    out-of-process one).
    """

    id: str
    name: str
    description: str = ""
    category: str = "general"
    # Subset of civex_plugin_sdk.protocol.CAPABILITIES this plugin actually
    # calls on ctx.
    capabilities: list[str] = []
    # The step-wiring contract: which `inputs:` keys a workflow step may
    # supply, and which output names other steps may reference as
    # `<step_id>.<output_name>`. `config` is *not* here -- it has its own
    # richer declaration as the `Config` model below, rendered to real JSON
    # Schema for `describe`.
    #
    # `None` and `[]` mean genuinely different things, and the host enforces
    # the difference: `[]` is a declaration -- "this plugin takes
    # no inputs" -- and wiring anything into it is an error, which is what
    # makes `<save_field_step>.result` a catchable mistake. `None` is the
    # absence of a declaration, and disables name checking in that direction
    # entirely. The default has to be `None` rather than `[]` so that a
    # plugin author who simply hasn't declared a contract yet doesn't hand
    # *workflow* authors confusing save-time rejections for a plugin that
    # runs fine.
    inputs: list[IOSpec] | None = None
    outputs: list[IOSpec] | None = None

    class Config(BaseModel):
        """A plugin's `run`-time configuration.

        Override with the fields this plugin actually accepts; the model is
        rendered to JSON Schema for `describe` and validated against the
        `run` frame's config dict before `invoke()` is called.
        """
