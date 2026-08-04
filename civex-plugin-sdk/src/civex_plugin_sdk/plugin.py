"""The base class every out-of-process (subprocess/container tier) plugin author subclasses.

A plugin declares its metadata (`id`, `name`, `inputs`, `outputs`, `Config`,
...) via `PluginBase` and implements `invoke()` here. `serve()`/
`serve_container()` are what actually instantiate the class and call
`invoke()` in response to a `run` frame -- a plugin author never calls it
themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from civex_plugin_sdk.ctx import Ctx
from civex_plugin_sdk.plugin_base import PluginBase


class Plugin(PluginBase, ABC):
    """Out-of-process plugin contract: `PluginBase`'s declarative surface plus the one method that actually does the work.

    Subclass this, set the `PluginBase` class attributes (`id`, `name`,
    `inputs`, `outputs`, `Config`, ...), and implement `invoke()`. Pass the
    subclass to `civex_plugin_sdk.serve()` (Tier 1) or `serve_container()`
    (Tier 2) -- nothing else needs to instantiate it.
    """

    @abstractmethod
    def invoke(
        self,
        inputs: dict[str, Any],
        config: Any,
        ctx: Ctx,
    ) -> dict[str, Any]:
        """Run this plugin for one workflow step.

        Args:
            inputs: Step inputs, keyed by name, already converted from the
                wire form to invoke-time values (e.g. a declared `table`
                input arrives as a pandas DataFrame, not the wire envelope).
            config: An instance of this plugin's `Config` model, already
                validated against the `run` frame's config dict.
            ctx: The RPC-backed handle for reading/writing records, files,
                schemas, and collections beyond what `inputs`/`config`
                already supplied.

        Returns:
            Step outputs, keyed by name, matching this plugin's declared
            `outputs` (when declared). Converted to the wire form
            automatically -- return a DataFrame or raw bytes directly for a
            `table`/`bytes` output.
        """
        ...
