# civex-plugin-sdk

SDK for authoring out-of-process [civex](https://github.com/CivexData/civex-service) workflow plugins — subprocess-tier (`uv run --script`) and container-tier plugins that run as an isolated OS process/container and talk to the host over an RPC wire protocol, rather than importing into civex's own process.

Subclass `Plugin`, declare its metadata, implement `invoke()`, and call `serve()`:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve


class Plugin(PluginBase):
    id = "my_project.compute_duration"   # must be unique; use a namespace prefix
    name = "Compute Duration"
    category = "transforms"              # informational only
    capabilities = ["get_context_record"]  # every ctx.* method this plugin calls

    class Config(BaseModel):
        start_field: str
        end_field: str

    def invoke(self, inputs: dict, config: Config, ctx: Ctx) -> dict:
        record = ctx.get_context_record()
        start = record["data"].get(config.start_field, 0)
        end = record["data"].get(config.end_field, 0)
        return {"duration": end - start}


if __name__ == "__main__":
    serve(Plugin)
```

Drop the file in `_civex/plugins/` in a civex project and it's discovered automatically. See [Writing a plugin](https://docs.civex.dev/extending/writing-a-plugin.html) for the full authoring guide (the `Ctx` API, isolation/timeouts, constraints), [Container plugins](https://docs.civex.dev/extending/container-plugins.html) for the Tier 2 path, and the [SDK reference](https://docs.civex.dev/extending/sdk-reference.html) for the complete public API.

## This package is not on PyPI

`pip install civex-plugin-sdk` does not work. The package is not published — the [release workflow](https://github.com/CivexData/civex-service/blob/main/.github/workflows/release.yml) builds and publishes only the civex application wheel, never this one.

The `dependencies = ["civex-plugin-sdk"]` line in the example above resolves anyway, but only inside a civex host that has this SDK's source checked out next to it (this repo's own workspace layout). When the host runs a plugin, it `uv build`s a wheel from its local `civex-plugin-sdk/` directory into a scratch directory and passes that as `--find-links`, so `uv run`'s resolver finds a package by that name without ever reaching an index. Outside such a checkout there is no local source to build, no `--find-links` override, and the dependency simply fails to resolve.

In short: plugin authors write `dependencies = ["civex-plugin-sdk"]` and it works *because they're running against a civex host that vendors this SDK's source*, not because the name is installable from PyPI. There is currently no supported way to `pip install` or `uv add` this package outside of that setup.

## Versioning

The SDK's version is hand-set in `pyproject.toml` (currently `0.2.0`) — it does not use setuptools-scm like the parent `civex` package does. `requires-python` is `>=3.10`, looser than civex's own `>=3.12`, since plugins run in their own subprocess/container environment independent of the host's interpreter.
