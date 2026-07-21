from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from civex_plugin_sdk.ctx import Ctx
from civex_plugin_sdk.plugin_base import PluginBase


class Plugin(PluginBase, ABC):
    @abstractmethod
    def invoke(
        self,
        inputs: dict[str, Any],
        config: Any,
        ctx: Ctx,
    ) -> dict[str, Any]: ...
