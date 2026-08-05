# The wire protocol

This is the reference [writing a plugin](writing-a-plugin.md) and [container plugins](container-plugins.md) both build on, and what makes it possible to write a plugin in a language the civex SDK doesn't exist for — a new-language starter only has to implement these frame shapes, not link against any civex code.

Newline-delimited JSON: one JSON object per line, in both directions over a single stdin/stdout pair — no length prefix. The host and the plugin process take turns; the protocol is strictly synchronous with no interleaving, so a blocking read for the next line is always sufficient on either side.

## Frame types

Every frame has a `"type"` field naming which of the following it is.

**Host → plugin**

| Type | Purpose |
|---|---|
| `describe` | "Tell me your contract." Carries no fields; the plugin responds with `describe_result`. |
| `run` | Run one workflow step: `{"type":"run","inputs":{...},"config":{...}}`. |
| `rpc_result` | The successful response to a plugin's `rpc_call`, matched by `call_id`: `{"type":"rpc_result","call_id":"...","result":{...}}`. |
| `error` | An `rpc_call` failed. Carries the same `error` envelope shape the plugin uses for its own failures. |

**Plugin → host**

| Type | Purpose |
|---|---|
| `describe_result` | The plugin's complete contract: `id`, `name`, `description`, `category`, `capabilities`, `inputs`/`outputs`, `config_schema`. Identical in shape for every tier, so no consumer (CLI `plugin info`, `GET /plugins`, the frontend plugin panel, the AI authoring guide) needs a per-tier branch. |
| `result` | `invoke()` succeeded: `{"type":"result","outputs":{...}}`. |
| `error` | A `run` (or `rpc_call`) failed: `{"type":"error","call_id":null,"error":{"kind":...,"message":...,"retryable":...}}`. `call_id` is set when this is a response to a specific `rpc_call`, unset for a top-level `run` failure. |
| `log` | A line of stdout/stderr output captured during `run`, relayed rather than left to corrupt the protocol stream. |
| `rpc_call` | Invoke one RPC method, blocking for the matching `rpc_result`/`error`: `{"type":"rpc_call","call_id":"...","method":"...","params":{...}}`. |

`error` is genuinely bidirectional — the host sends it in response to a failed `rpc_call`, the plugin sends it in response to a failed `describe`/`run` or to report an RPC failure it can't otherwise express. Both directions share the one `ErrorFrame` shape.

## Two dispatch models

Both tiers speak identical frames; only *how the process is invoked* differs.

**Tier 1 (subprocess) — persistent process.** The host spawns `uv run --no-project <plugin>.py` once and keeps it alive for the whole run. The plugin loops reading frames off real stdin, dispatching on each one's `type` (`describe` or `run`), and can be asked to describe itself and then run in the same process lifetime. This is `civex_plugin_sdk.serve()` (`serve_loop` internally).

**Tier 2 (container) — one process per operation.** The host runs `docker run -i <image> <mode>`, where `<mode>` is `describe` or `run`, passed as `sys.argv[1]` rather than inferred from the first frame — a fresh container per call is what lets per-run `--memory`/`--cpus` limits and the timeout/kill wrapper apply per operation rather than for the container's whole lifetime. The plugin reads exactly one frame (matching the requested mode) and exits. This is `civex_plugin_sdk.serve_container()` (`serve_container_once` internally) — same frame parsing, same RPC dispatch, same stdout isolation as Tier 1, just single-shot instead of looping.

## `isolate_stdout()`: keeping stray output off the wire

Before any plugin code runs, the SDK duplicates the real stdout file descriptor (fd 1) to a private fd, then redirects the *public* fd 1 to `/dev/null`. Every protocol frame is written through that private duped fd (`FrameWriter`), never through the public one. A stray `print()`, a warning from an imported library, or debug output from your own code all go to `/dev/null` — they can never interleave with, or corrupt, the JSON on the wire. `ctx.log()` is the supported replacement for anything you actually want the host to see: it sends a `log` frame down the real protocol channel instead.

Every language's starter (including the non-Python ones — see [Container plugins](container-plugins.md)) reimplements this same fd-dup trick before any author code runs, since it's what makes the wire safe regardless of what libraries a plugin happens to import.

## Binary payloads: inline or scratch file

Binary values (`bytes` outputs, `get_file` results) are base64-inlined directly in the frame when they're small, and above `BINARY_INLINE_THRESHOLD` (1 MB) written to a scratch path instead — the frame then carries `{"encoding": "path", "path": "..."}` rather than the bytes themselves. Below the threshold, the envelope is `{"encoding": "base64", "data": "..."}`. This keeps a single oversized file from blowing up an otherwise-small JSON line, while small payloads avoid a filesystem round-trip.

## `table` and `bytes` on the wire

Declared `table`/`bytes` `IOSpec` values cross the wire through one shared conversion (`civex_plugin_sdk.io_convert`), used identically by every tier so a plugin author's code never has to know or care which one it's running under:

- **`bytes`** crosses as the same inline-or-scratch-path envelope described above.
- **`table`** crosses as columnar, typed records: `{"encoding": "inline", "columns": [...], "dtypes": {col: civex_type}, "data": {col: [values...]}}` when small, or `{"encoding": "ndjson_path", "path": "..."}` above a row-count threshold (one JSON row object per line, first line a `{"columns": ..., "dtypes": ...}` header) — so a step that's merely relaying a table between two other steps never has to hold or embed the full contents, only whichever step actually reads it does. `dtypes` reuses civex's own scalar field vocabulary (`integer`/`float`/`string`/`boolean`/`date`/`datetime`), not a pandas-specific one, so a table means the same thing here as everywhere else in civex and round-trips through non-Python tiers with no pandas-specific knowledge required on their end.

A Python plugin author never sees either envelope directly — a `table` input arrives as a real pandas DataFrame, a `bytes` input as real `bytes`; the SDK converts back to the wire form on the way out.

## Capabilities

A plugin declares the `ctx.*` methods it calls via its `capabilities` list, returned as part of `describe_result`. That list is captured once, **at discovery time** — when the host first spawns the plugin to ask it to describe itself — and is what gets passed into `run_plugin(...)`/`run_container(...)` for every subsequent run. It is never re-derived from the live process making the RPC calls: a plugin that declared a narrow `capabilities` list at discovery but tries to call something wider at run time is exactly the case this is meant to catch, and it fails with a `capability_denied` error rather than being silently permitted because the running process asked nicely.

RPC methods on the wire are `get_file`, `update_record`, `create_record`, `commit`, plus one generic **`call_tool`** that carries every other capability (`get_context_record`, `find_records`, `get_schema`, `store_file`, ...) without a protocol change — `call_tool`'s `params` are always `{"tool": <tool name>, "args": {...}}`. Because of this, a plugin's declared `capabilities` name the **tool**, not the literal string `"call_tool"` — a plugin using `ctx.find_records()` declares `capabilities = ["find_records"]`, never `capabilities = ["call_tool"]`. Enforcement checks `params["tool"]` against the declared list for a `call_tool` request, and the bare method name for the other four.

For tier BUILTIN (in-process built-in plugins), capabilities are metadata only — there's no RPC boundary to intercept, since a built-in's `invoke()` calls the real `WorkflowContext` directly rather than going over stdin/stdout. Declaring `capabilities` on a built-in documents what it does but doesn't gate anything at run time.
