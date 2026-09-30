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

Drop the file in `_civex/plugins/` in a civex project and it's discovered automatically. See [Writing a plugin](https://civexdata.github.io/civex-docs/extending/writing-a-plugin.html) for the full authoring guide (the `Ctx` API, isolation/timeouts, constraints), [Container plugins](https://civexdata.github.io/civex-docs/extending/container-plugins.html) for the Tier 2 path, and the [SDK reference](https://civexdata.github.io/civex-docs/extending/sdk-reference.html) for the complete public API.

## Installing

```bash
pip install civex-plugin-sdk          # or: uv add civex-plugin-sdk
pip install "civex-plugin-sdk[table]" # adds pandas for `table`-typed inputs/outputs
```

In a plugin script the PEP 723 header is all you need — `uv run` resolves it. When civex runs the plugin it pins the SDK to the version civex itself uses, so you don't pin it yourself.

## Versioning

The SDK's version is hand-set in `pyproject.toml` and bumped on every change under `src/` (CI enforces this) — it does not use setuptools-scm like the parent `civex` package does. `requires-python` is `>=3.10`, looser than civex's own `>=3.12`, since plugins run in their own subprocess/container environment independent of the host's interpreter.

The wire protocol has its own number, `civex_plugin_sdk.PROTOCOL_VERSION`, which changes only for breaking wire changes; civex refuses a plugin whose protocol it doesn't speak. See [CHANGELOG.md](CHANGELOG.md) and the maintainer guide `docs/contributing/sdk-release.md` in the civex repo.

## License

MIT — see [LICENSE](LICENSE). (The `civex` application itself is under a different license.)
