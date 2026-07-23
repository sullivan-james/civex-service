"""Starter template for a Tier 2 (container) civex plugin.

Rename `Plugin.id`/`name`/`category`, declare `capabilities`/`Config`, and
implement `invoke()` -- civex_plugin_sdk.serve_container handles the wire
protocol (frame parsing, the fd-dup stdout isolation trick, rpc_call
dispatch), the same SDK Tier 1 (subprocess) plugins use.

The host runs the built image as `docker run -i <image> describe` or
`docker run -i <image> run`; serve_container reads that mode from argv and,
for `run`, reads one `{"inputs": ..., "config": ...}` frame from stdin.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from civex_plugin_sdk import Ctx, Plugin, serve_container


class MyPlugin(Plugin):
    id = "my_project.my_container_plugin"  # must be unique; use a namespace prefix
    name = "My Container Plugin"
    category = "transforms"  # informational only
    capabilities: list[str] = []  # every ctx.* method this plugin calls

    class Config(BaseModel):
        pass

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        return {}


if __name__ == "__main__":
    serve_container(MyPlugin)
