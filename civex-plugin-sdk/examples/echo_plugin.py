#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
"""Minimal reference plugin exercising the full protocol surface: describe,
run, config validation, and one rpc_call (commit) when asked to.

In a real subprocess-tier deployment this file is invoked via
`uv run --script echo_plugin.py`, which resolves `civex-plugin-sdk` from the
PEP 723 header above with no manual environment setup. This repo's own
tests invoke it directly (the SDK is already on the path via the uv
workspace venv) to exercise the wire protocol over a real subprocess
boundary without needing a published package.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from civex_plugin_sdk import Ctx, Plugin, serve


class EchoPlugin(Plugin):
    id = "example.echo"
    name = "Echo"
    category = "example"
    capabilities = ["commit"]

    class Config(BaseModel):
        text: str

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        if inputs.get("call_commit"):
            ctx.commit()
        return {"echo": config.text, "inputs": inputs}


if __name__ == "__main__":
    serve(EchoPlugin)
