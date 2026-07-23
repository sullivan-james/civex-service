# Rust starter: Tier 2 (container) civex plugin

A minimal Rust shim implementing civex's plugin wire protocol -- the same
newline-delimited JSON frames over stdin/stdout that the Tier 1
(subprocess) Python SDK uses (see `civex-plugin-sdk/`), spoken by a
container instead of a `uv run` subprocess. Use this as the starting point
for a plugin that needs something Python-level isolation can't give: a
different language, a system binary, GPU access, or resource limits.

## Layout

```
civex-plugin.toml   manifest civex's registry reads: id/name/category/capabilities
Dockerfile           builds this directory into a runnable image
Cargo.toml
src/
  main.rs            entrypoint: stdout isolation + describe/run dispatch
  protocol.rs         frame shapes (mirrors civex_plugin_sdk.protocol)
  io.rs               fd-dup stdout isolation + newline-delimited JSON I/O
  ctx.rs              the Ctx capability client (mirrors civex_plugin_sdk.ctx)
  plugin.rs           <-- the actual plugin; edit this file
```

## Using this template

1. Copy this whole directory to `_civex/plugins/<your-plugin-name>/` in your
   project.
2. Edit `src/plugin.rs`: change `ID`/`NAME`/`DESCRIPTION`/`CATEGORY`,
   `Config`, `inputs()`/`outputs()`, and `run()` to do what your plugin
   needs. Everything below the `Shim plumbing` marker in that file shouldn't
   need to change.
3. Update `civex-plugin.toml` to match `ID`/`NAME`/`CATEGORY`/`CAPABILITIES`.
4. Add whatever else your plugin needs (extra crates in `Cargo.toml`, system
   packages in the `Dockerfile`'s final stage, ...).

## The wire protocol

This process is invoked as `docker run -i <image> <mode>`, where `<mode>` is
either `describe` or `run` -- one container per operation, same as how the
Tier 1 runtime spawns one fresh `uv run` process per `describe`/`run` rather
than keeping one alive across both.

- **`describe`**: no stdin required. Writes one `describe_result` frame
  (`id`, `name`, `capabilities`, `config_schema`, ...) and exits.
- **`run`**: reads one JSON line from stdin shaped like
  `{"inputs": {...}, "config": {...}}`, executes the plugin (which may
  exchange `rpc_call`/`rpc_result` frames with the host along the way to use
  a declared capability, e.g. `ctx.commit()`), then writes one `result` or
  `error` frame and exits.

All frames are single JSON objects, one per line. Before any of this runs,
`main()` calls `io::isolate_stdout()`, which dup's the real stdout fd to a
private one and redirects public fd 1 to `/dev/null` -- so a stray
`println!`/panic message from your plugin logic can't corrupt the protocol
stream. All protocol writes go through that private fd (`FrameWriter`),
never through `std::io::stdout()`.

## Building and testing locally

```bash
cd _civex/plugins/<your-plugin-name>
cargo build --release

# describe
./target/release/civex-plugin describe

# run
echo '{"inputs": {}, "config": {"text": "hello"}}' | ./target/release/civex-plugin run
```

The example `echo` plugin this template ships with should print a
`describe_result` frame and, for the `run` example above, a
`{"type":"result","outputs":{"echo":"hello","inputs":{}}}` frame.
