"""SDK for authoring out-of-process (subprocess/container tier) civex workflow plugins.

Subclass `Plugin`, declare `id`/`name`/`inputs`/`outputs`/`Config`,
implement `invoke()`, and call `serve()` (Tier 1) or `serve_container()`
(Tier 2) from the plugin script's `__main__` -- see
docs/extending/writing-a-plugin.md for the full authoring guide.
"""

from civex_plugin_sdk.ctx import Ctx
from civex_plugin_sdk.errors import (
    CapabilityDeniedError,
    ConfigValidationError,
    PluginError,
    RpcError,
)
from civex_plugin_sdk.plugin import Plugin
from civex_plugin_sdk.plugin_base import IO_TYPES, IOSpec, PluginBase
from civex_plugin_sdk.serve import serve, serve_container

__all__ = [
    "Ctx",
    "IOSpec",
    "IO_TYPES",
    "Plugin",
    "PluginBase",
    "serve",
    "serve_container",
    "PluginError",
    "CapabilityDeniedError",
    "ConfigValidationError",
    "RpcError",
]
