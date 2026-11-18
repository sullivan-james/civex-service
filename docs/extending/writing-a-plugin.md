# Writing a plugin

You can extend civex with your own plugins. Place a `.py` file in `_civex/plugins/` and civex discovers it automatically — no registration required.

Custom plugins run as **real, isolated OS processes** (`uv run --no-project <plugin>.py`), not imported into civex's own process. Each run gets its own dependency environment (declared inline in the file — no editing civex's own `pyproject.toml`, ever), its own process group (killed as a unit if it exceeds its timeout), a throwaway working directory with no ambient path into your project data, and access to project data *only* through the RPC calls it explicitly declares.

This is the Tier 1 (subprocess) path — Python only, run via `uv run`. If you need a different language, system binaries, GPU access, or stricter resource limits, see [Container plugins](container-plugins.md) instead. Both tiers speak the same [wire protocol](wire-protocol.md).

## Minimal example

```python title="civex-plugin-sdk/examples/echo_plugin.py"
--8<-- "civex-plugin-sdk/examples/echo_plugin.py"
```

Use it in a workflow:

```yaml
- id: compute
  plugin: example.echo
  config:
    text: hello
  timeout: 30   # optional; overrides [plugins].default_timeout_seconds from config.toml

- id: save
  plugin: civex.save_field
  config:
    field: greeting
  inputs:
    value: compute.echo
```

!!! note "Which SDK version does my plugin get?"
    `civex-plugin-sdk` is a normal PyPI package (MIT licensed), so the plain
    `dependencies = ["civex-plugin-sdk"]` line resolves like any other. When
    civex first starts your plugin it **locks** its dependencies
    (`uv lock --script`, a `<plugin>.py.lock` file beside it), and from then
    on runs exactly those versions, without asking a package index, until you
    change the dependencies. Updating civex doesn't rebuild the plugin's
    environment: civex speaks every wire protocol version from 1 to its own,
    and refuses a plugin on a newer one with a message saying which side to
    upgrade. Delete the lockfile to take newer versions.

## The header: what civex knows without running the plugin

When you save a plugin from the app (or run `civex plugin check --write
<plugin>.py`), civex asks it once what it is and writes the answer into the
script block at the top of the file, under `[tool.civex]`: its id, name,
capabilities, inputs, outputs and config schema. From then on civex knows the
plugin by reading that, without running it (discovery, the workflow checks,
the shared library). Don't edit it by hand: change the code and save again.

When the plugin's process starts, civex asks the code again, and refuses to
run a plugin whose code no longer says what its header does (it asks for a
capability the header doesn't grant, say) until the header is written again
from the code. `civex plugin check <plugin>.py` says whether they agree. A
plugin with no header is described by running it, as before.

## Plugin structure

Every plugin file must:

1. Start with a [PEP 723](https://peps.python.org/pep-0723/) inline script metadata block declaring `civex-plugin-sdk` as a dependency (plus anything else the plugin needs — `pandas`, `requests`, whatever). `uv run` resolves and caches an isolated venv for it automatically, the first time it's used, and civex locks what it resolved (see above). civex adds the `[tool.civex]` header to this block when you save.
2. Define a class subclassing the SDK's `Plugin` ABC (import it directly, or under an alias like `Plugin as PluginBase` if you want to name your own subclass `Plugin` too).
3. Call `serve(YourPluginClass)` inside `if __name__ == "__main__":`.

| Attribute | Type | Description |
|---|---|---|
| `id` | string | Unique identifier used in workflow YAML. Prefix with your project name to avoid collisions. |
| `name` | string | Human-readable name shown in the UI. |
| `category` | string | Informational grouping. No functional effect. |
| `capabilities` | list[string] | The permission actions the plugin needs (`"read"`, `"write_records"`, `"manage_files"`, `"delete"`; see [The Ctx API](#the-ctx-api)). A call it wasn't granted fails at run time with a `capability_denied` error — the host enforces this against the list your plugin declared at discovery time, not anything the running process claims about itself. See [Capabilities](wire-protocol.md#capabilities) for how this is enforced on the wire. |

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

`Ctx` is deliberately more restrictive than a plain in-process object: it has **no ambient `.record`/`.dataset`** — a plugin can't accidentally read anything it wasn't granted. Everything goes over an RPC call to the host, checked against what the plugin's `capabilities` grant before it runs.

**Capabilities are permission actions.** List the ones your plugin needs; each grants every method in its row below. (Naming a single method instead, `capabilities = ["find_records"]`, grants just that one: the older form, still read.) Whatever is granted, the call is also held to what the person running the workflow may do in the project.

| Needs | Methods |
|---|---|
| `read` | `ctx.get_context_record()` (the record the run is for: `id`, `schema_id`, `data`, ...; the only way to learn it), `ctx.get_context_dataset()` (its collection), `ctx.get_record(record_id)`, `ctx.find_records(dataset_name, schema_name=None, parent_record_id=None, filters=None, search=None, limit=50, offset=0)`, `ctx.get_file(sha256)` (a stored file's bytes), `ctx.file_path(sha256)` (a read-only copy of a stored file in the run's folder, as a path: nothing read into memory; use this for large files), `ctx.get_schema(name)`, `ctx.list_schemas()`, `ctx.get_collection(name)`, `ctx.list_collections()` |
| `write_records` | `ctx.patch_record(record_id, fields)` (change only these fields; writes nothing when they already hold these values: use this), `ctx.update_record(record_id, data)` (**replaces** the record's data: fields left out are cleared), `ctx.create_record(dataset_name, schema_name, data, context_record_id=None)` (inside the run's record unless told otherwise; triggers fire for it as usual) |
| `manage_files` | `ctx.store_file(data, filename)` (store bytes in the run's collection; returns a `FileRef`-shaped dict), `ctx.store_path(path, filename)` (store a file you wrote in the run's folder, `ctx.run_dir`; read by civex itself, so large files never pass through the protocol) |
| `delete` | `ctx.delete_record(record_id)` (it can be restored from Activity) |

These need nothing, since they read and change nothing of the project's:

| Method | Description |
|---|---|
| `ctx.progress(done, total=None, message="")` | Say how far the run has got ("Reading sel_03.txt", 3 of 12). The app shows it in the status bar while the run lasts. |
| `print(...)` | Goes to the run's log (see the run's page), as does anything written to stderr. |

**There is no commit.** A run's writes are kept when every step succeeds and all undone if one fails, so a failed run never leaves records half-changed. (`ctx.commit()` still exists for plugins written before, and does nothing.)

See the [SDK reference](sdk-reference.md) for the full generated API, including exact signatures and return types.

### Reading and writing the trigger record

```python
record = ctx.get_context_record()
value = record["data"].get("reading")   # None if not set

ctx.patch_record(record["id"], {"duration": 42.5})   # only this field changes
```

Or use `civex.save_field` / `civex.save_fields` as separate workflow steps instead of calling `ctx.update_record` directly.

### The run's folder

Each workflow run has a folder of its own, removed when the run ends (`ctx.run_dir`). The files a plugin asks for (`ctx.file_path`, `ctx.get_file`) are copied there, and any `table` or `bytes` value too large to send inline is written there, so a later step can read what an earlier one wrote. A plugin may hand back only files inside that folder (or its own working folder): civex refuses a path anywhere else (`path_refused`).

### Accessing files

```python
record = ctx.get_context_record()
ref = record["data"].get("reading")   # {"sha256": "...", "filename": "...", "size": ...}
if ref:
    raw_bytes = ctx.get_file(ref["sha256"])
```

## Isolation and timeouts

- A plugin runs as a `uv run --no-project` subprocess with its own process group, killed as a unit (SIGTERM, then SIGKILL if it doesn't exit) if it exceeds its timeout.
- The process is **kept between runs**: once started (or asked to describe itself), it answers the next run of the same plugin too, until it has been idle for five minutes or civex stops. Editing the file starts a new one. So module-level state in your plugin lives from one run to the next; anything a run must not see from the last belongs inside `invoke()`. A process that times out or dies is not reused.
- Default timeout is `[plugins].default_timeout_seconds` in `_civex/config.toml` (60s if unset); override per step with `timeout: <seconds>` on the workflow step.
- The subprocess's working directory is a throwaway scratch dir, emptied before each run, never your project's `_civex/` — a plugin has no ambient filesystem path into real project data, only what it fetches over the `ctx.*` capability calls it declared.
- The subprocess's environment is minimal (`PATH`, `HOME`, a few uv/Python variables) — it can't read civex's own environment (database URL, AI API keys, ...).

## Constraints

- Plugins run as separate OS processes, not imported into civex's own process — they never import `civex.*` modules directly, only `civex_plugin_sdk`.
- A plugin can only reach project data through the `ctx.*` calls it declared in `capabilities`; anything else fails with `capability_denied`.
- All changes are committed together at the end of the workflow run unless you call `ctx.commit()` explicitly.
- If `invoke()` raises an exception (or the run times out), the entire workflow job is marked as failed and no changes are committed.

## Next steps

- [Container plugins](container-plugins.md) — a different language, or stricter isolation than a subprocess gives you.
- [The wire protocol](wire-protocol.md) — the frame-by-frame reference `serve()` implements underneath `invoke()`.
- [SDK reference](sdk-reference.md) — the full generated `civex_plugin_sdk` API.
