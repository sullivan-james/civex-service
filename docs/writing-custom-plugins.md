# Writing custom plugins

You can extend civex with your own plugins. Place a `.py` file in `_civex/plugins/` and civex discovers it automatically — no registration required.

Custom plugins run as **real, isolated OS processes** (`uv run --no-project <plugin>.py`), not imported into civex's own process. Each run gets its own dependency environment (declared inline in the file — no editing civex's own `pyproject.toml`, ever), its own process group (killed as a unit if it exceeds its timeout), a throwaway working directory with no ambient path into your project data, and access to project data *only* through the RPC calls it explicitly declares.

## Minimal example

```python
# _civex/plugins/compute_duration.py
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

Use it in a workflow:

```yaml
- id: compute
  plugin: my_project.compute_duration
  config:
    start_field: begin_time
    end_field: end_time
  timeout: 30   # optional; overrides [plugins].default_timeout_seconds from config.toml

- id: save
  plugin: civex.save_field
  config:
    field: duration
  inputs:
    value: compute.duration
```

## Plugin structure

Every plugin file must:

1. Start with a [PEP 723](https://peps.python.org/pep-0723/) inline script metadata block declaring `civex-plugin-sdk` as a dependency (plus anything else the plugin needs — `pandas`, `requests`, whatever). `uv run` resolves and caches an isolated venv for it automatically, the first time it's used.
2. Define a class named exactly `Plugin`, subclassing the SDK's own `Plugin` ABC (import it under an alias — `Plugin as PluginBase` — to avoid the name collision).
3. Call `serve(Plugin)` inside `if __name__ == "__main__":`.

| Attribute | Type | Description |
|---|---|---|
| `id` | string | Unique identifier used in workflow YAML. Prefix with your project name to avoid collisions. |
| `name` | string | Human-readable name shown in the UI. |
| `category` | string | Informational grouping. No functional effect. |
| `capabilities` | list[string] | Every `ctx.*` method this plugin calls, by name (e.g. `"find_records"`, not the literal string `"call_tool"`). A call to an undeclared capability fails at run time with a `capability_denied` error — the host enforces this against the list your plugin declared at discovery time, not anything the running process claims about itself. |

### Config

Declare a `Config` class that inherits from `pydantic.BaseModel`. Its fields become the keys in the step's `config:` block. Pydantic handles type coercion and validation automatically — validated for real inside your plugin's own process, not just checked against a JSON schema at save time.

```python
class Config(BaseModel):
    field: str
    multiplier: float = 1.0         # optional with default
    mode: str = "linear"
```

### `invoke()`

```python
def invoke(
    self,
    inputs: dict,   # values from input references
    config: Config,  # validated config from the workflow YAML
    ctx: Ctx,        # RPC client for the capabilities you declared
) -> dict:
    ...
    return {"output_name": value}
```

Return a dict of output values. These are referenced by downstream steps as `this_step_id.output_name`. Return an empty dict `{}` if the step produces no outputs.

!!! warning
    If `invoke()` raises, the whole workflow job is marked failed and no changes made by earlier steps in the same run are committed (the executor commits once, at the end, after every step succeeds).

## The Ctx API

`Ctx` is deliberately more restrictive than a plain in-process object: it has **no ambient `.record`/`.dataset`** — a plugin can't accidentally read anything it wasn't given a capability for. Everything goes over an RPC call to the host, capability-checked before it's allowed to run.

| Method | Capability name | Description |
|---|---|---|
| `ctx.get_context_record() → dict` | `get_context_record` | The record that triggered this workflow (`id`, `schema_id`, `data`, ...). This is how a plugin learns what triggered it — there's no ambient `.record` field. |
| `ctx.get_context_dataset() → dict` | `get_context_dataset` | The dataset the trigger record belongs to. |
| `ctx.get_file(sha256: str) → bytes` | `get_file` | Retrieve a stored file's bytes by hash. |
| `ctx.store_file(data: bytes, filename: str) → dict` | `store_file` | Store bytes as a new file object; returns a `FileRef`-shaped dict. |
| `ctx.update_record(record_id: str, data: dict) → dict` | `update_record` | Write `data` into any record by id (not just the trigger — pass the trigger's id from `get_context_record()` to update it). Merges into existing data. |
| `ctx.create_record(dataset_name, schema_name, data, context_record_id=None) → dict` | `create_record` | Create a new record; triggers fire for it as normal. `context_record_id` defaults to the trigger record when omitted. |
| `ctx.get_record(record_id: str) → dict` | `get_record` | Fetch any record by id. |
| `ctx.find_records(dataset_name, schema_name=None, parent_record_id=None, filters=None, search=None, limit=50, offset=0) → list[dict]` | `find_records` | Query records. |
| `ctx.delete_record(record_id: str)` | `delete_record` | Delete a record. |
| `ctx.get_schema(name: str) → dict`, `ctx.list_schemas() → list[dict]` | `get_schema`, `list_schemas` | Read-only schema introspection. |
| `ctx.get_collection(name: str) → dict`, `ctx.list_collections() → list[dict]` | `get_collection`, `list_collections` | Read-only dataset (collection) introspection. |
| `ctx.commit()` | `commit` | Flush pending changes to the database. The executor also commits once at the end of a successful run; call this yourself only if you need an intermediate commit. |

Declare each one you use in `capabilities` — see the table above for the exact capability name per method.

### Reading and writing the trigger record

```python
record = ctx.get_context_record()
value = record["data"].get("audio_file")   # None if not set

ctx.update_record(record["id"], {"duration": 42.5})   # merges into existing data
```

Or use `civex.save_field` / `civex.save_fields` as separate workflow steps instead of calling `ctx.update_record` directly.

### Accessing files

```python
record = ctx.get_context_record()
ref = record["data"].get("audio_file")   # {"sha256": "...", "filename": "...", "size": ...}
if ref:
    raw_bytes = ctx.get_file(ref["sha256"])
```

## Isolation and timeouts

- Each run is a fresh `uv run --no-project` subprocess with its own process group, killed as a unit (SIGTERM, then SIGKILL if it doesn't exit) if it exceeds its timeout.
- Default timeout is `[plugins].default_timeout_seconds` in `_civex/config.toml` (60s if unset); override per step with `timeout: <seconds>` on the workflow step.
- The subprocess's working directory is a throwaway scratch dir, never your project's `_civex/` — a plugin has no ambient filesystem path into real project data, only what it fetches over the `ctx.*` capability calls it declared.
- The subprocess's environment is minimal (`PATH`, `HOME`, a few uv/Python variables) — it can't read civex's own environment (database URL, AI API keys, ...).

## Constraints

- Plugins run as separate OS processes, not imported into civex's own process — they never import `civex.*` modules directly, only `civex_plugin_sdk`.
- A plugin can only reach project data through the `ctx.*` calls it declared in `capabilities`; anything else fails with `capability_denied`.
- All changes are committed together at the end of the workflow run unless you call `ctx.commit()` explicitly.
- If `invoke()` raises an exception (or the run times out), the entire workflow job is marked as failed and no changes are committed.

## Container-tier (Tier 2) plugins

For a plugin that needs something the subprocess tier can't give — a different language, system binaries, GPU access, stricter resource limits — civex will run it inside a Docker container instead, using the same `id`/`name`/`capabilities`/`Config`/`invoke()` shape and the same wire protocol described above. A Python starter (Dockerfile + `plugin.py` shim) lives in `templates/container-plugins/python/`; copy it into `_civex/plugins/<name>/` alongside a `civex-plugin.toml` manifest (`id`/`name`/`category`/`capabilities`) and fill in `invoke()`.

The one difference from the subprocess tier: `civex_plugin_sdk.serve_container` (instead of `serve`) is called from `__main__`, since a container is invoked once per operation (`docker run -i <image> describe` or `docker run -i <image> run`) rather than as a long-lived process — it reads that mode from `sys.argv[1]` instead of from a leading control frame on stdin.
