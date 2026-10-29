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
| `log` | A line the plugin printed: `{"type":"log","stream":"stdout","text":"..."}`. The host writes it to the run's log. No answer. |
| `progress` | How far the current `run` has got: `{"type":"progress","done":3,"total":12,"message":"Reading sel_03.txt"}` (`total` may be null). The app shows it in the status bar while the run lasts. No answer. Protocol 2. |
| `rpc_call` | Invoke one RPC method, blocking for the matching `rpc_result`/`error`: `{"type":"rpc_call","call_id":"...","method":"...","params":{...}}`. |

`error` is genuinely bidirectional — the host sends it in response to a failed `rpc_call`, the plugin sends it in response to a failed `describe`/`run` or to report an RPC failure it can't otherwise express. Both directions share the one `ErrorFrame` shape.

## How a plugin is started

Every plugin speaks identical frames; only *how it is started* differs, and that is all a tier is in civex (a *launcher*, `civex.plugins.launchers`). The host drives every one the same way (`civex.plugins.runtime`).

**Built-in — a thread in civex.** civex's own plugins are SDK `Plugin`s served by `serve_loop` on a thread of civex's process, over in-memory streams of the same JSON frames, kept between runs like a subprocess. Trusted code: not stopped by a step's timeout.

**Tier 1 (subprocess) — persistent process.** The host spawns `uv run --no-project <plugin>.py` once and keeps it alive across runs: the same process answers the `describe` at discovery and every later `run` of that plugin, until it has been idle for a while (`civex.plugins.workers`). A process that timed out, died or sent a malformed frame is stopped instead of reused. The plugin loops reading frames off real stdin, dispatching on each one's `type` (`describe` or `run`), and can be asked to describe itself and then run in the same process lifetime. This is `civex_plugin_sdk.serve()` (`serve_loop` internally).

**Tier 2 (container) — one process per operation.** The host runs `docker run -i <image> <mode>`, where `<mode>` is `describe` or `run`, passed as `sys.argv[1]` rather than inferred from the first frame — a fresh container per call is what lets per-run `--memory`/`--cpus` limits and the timeout/kill wrapper apply per operation rather than for the container's whole lifetime. The plugin reads exactly one frame (matching the requested mode) and exits. This is `civex_plugin_sdk.serve_container()` (`serve_container_once` internally) — same frame parsing, same RPC dispatch, same stdout isolation as Tier 1, just single-shot instead of looping.

## `isolate_stdout()`: keeping stray output off the wire

Before any plugin code runs, the SDK duplicates the real stdout file descriptor (fd 1) to a private fd, then redirects the *public* fd 1 to `/dev/null`. Every protocol frame is written through that private duped fd (`FrameWriter`), never through the public one, so output can never interleave with, or corrupt, the JSON on the wire.

`sys.stdout` is then replaced by a `LogStream`, which sends each line written to it as a `log` frame: a `print()` from your plugin reaches the run's log, in order with the run's other frames (a half-printed line is sent before the run's answer). Only output written straight to fd 1 by C code is lost. Anything written to stderr (warnings, the `logging` module's default handler, a traceback) is read by the host as it comes and also goes to the run's log; the last lines of it are kept for the message when a plugin process dies.

## Versions

`describe_result` carries the `protocol_version` the plugin's SDK speaks (absent means 1). The host runs a plugin whose version is anywhere from 1 to its own, since each version so far only added what a plugin *may* send; it refuses a newer one with a message saying to update civex.

| Version | Change |
|---|---|
| 1 | The frames above, less `progress`. |
| 2 | `progress` frames. |

## Binary payloads: inline or scratch file

Binary values (`bytes` outputs, `get_file` results) are base64-inlined directly in the frame when they're small, and above `BINARY_INLINE_THRESHOLD` (1 MB) written to a scratch path instead — the frame then carries `{"encoding": "path", "path": "..."}` rather than the bytes themselves. Below the threshold, the envelope is `{"encoding": "base64", "data": "..."}`. This keeps a single oversized file from blowing up an otherwise-small JSON line, while small payloads avoid a filesystem round-trip.

## `table` and `bytes` on the wire

Declared `table`/`bytes` `IOSpec` values cross the wire through one shared conversion (`civex_plugin_sdk.io_convert`), used identically by every tier so a plugin author's code never has to know or care which one it's running under:

- **`bytes`** crosses as the same inline-or-scratch-path envelope described above.
- **`table`** crosses as columnar, typed records: `{"encoding": "inline", "columns": [...], "dtypes": {col: civex_type}, "data": {col: [values...]}}` when small, or `{"encoding": "ndjson_path", "path": "..."}` above a row-count threshold (one JSON row object per line, first line a `{"columns": ..., "dtypes": ...}` header) — so a step that's merely relaying a table between two other steps never has to hold or embed the full contents, only whichever step actually reads it does. `dtypes` reuses civex's own scalar field vocabulary (`integer`/`float`/`string`/`boolean`/`date`/`datetime`), not a pandas-specific one, so a table means the same thing here as everywhere else in civex and round-trips through non-Python tiers with no pandas-specific knowledge required on their end.

A Python plugin author never sees either envelope directly — a `table` input arrives as a real pandas DataFrame, a `bytes` input as real `bytes`; the SDK converts back to the wire form on the way out.

## Capabilities

A plugin declares what it needs via its `capabilities` list, returned as part of `describe_result`. That list is captured once, **at discovery time** — when the host first spawns the plugin to ask it to describe itself — and is what gets passed into `run_plugin(...)`/`run_container(...)` for every subsequent run. It is never re-derived from the live process making the RPC calls: a plugin that declared a narrow `capabilities` list at discovery but tries to call something wider at run time is exactly the case this is meant to catch, and it fails with a `capability_denied` error rather than being silently permitted because the running process asked nicely.

RPC methods on the wire are `get_file`, `update_record`, `create_record`, `commit`, plus one generic **`call_tool`** that carries every other host function (`get_context_record`, `find_records`, `patch_record`, `store_file`, ...) without a protocol change — `call_tool`'s `params` are always `{"tool": <name>, "args": {...}}`. On the host a method and a tool are the same thing: a name in one table of host functions (`civex.plugins.host_api`), each needing a permission action. A plugin's `capabilities` list those actions (`read`, `write_records`, `manage_files`, `delete`), or, in the older form, single function names; the host works out once, at discovery, which functions that grants, and refuses any other with `capability_denied`. `commit` is answered and does nothing: the host keeps a run's writes when it ends, or none of them if a step failed.

Built-in plugins are held to the same rule. They are SDK `Plugin`s too, run in civex's own process by the SDK's `serve_loop` on a thread, over in-memory streams carrying the same JSON frames (`civex.plugins.launchers.InProcessLauncher`), so a built-in reaches the project only through the host functions its `capabilities` grant, exactly as a plugin in a process does. Unlike one, it isn't stopped by a step's timeout: a thread can't be killed.
