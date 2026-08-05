# Java plugin starter (Tier 2 / container)

A starting point for a container-tier plugin written in Java. Copy this
whole directory into `_civex/plugins/<name>/` in your project and edit:

- `civex-plugin.toml` — `id`/`name`/`category`/`capabilities`
- `Main.java` — the `PLUGIN_*` constants, `configSchema()`, and `invoke()`

## Layout

```
_civex/plugins/<name>/
  civex-plugin.toml   # manifest
  Dockerfile           # build context is this directory
  entrypoint.sh         # fd-dup isolation, then execs the JVM
  Main.java             # protocol plumbing + your invoke() logic
```

## Protocol

`Main` speaks the same newline-delimited JSON protocol over stdin/stdout as
a Tier 1 (subprocess) plugin from `civex-plugin-sdk` — see
[`docs/extending/wire-protocol.md`](../../docs/extending/wire-protocol.md) for
the frame shapes (`describe`/`describe_result`, `run`/`result`/`error`,
`rpc_call`/`rpc_result`). The one difference from Tier 1 is how the mode is
selected: instead of a persistent process that dispatches on the first
frame it reads, the container is invoked once per call as
`docker run -i <image> <mode>`, with `<mode>` being `describe` or `run`.
`entrypoint.sh` forwards that argument straight to `Main`.

Because Java has no portable `dup2()`, the fd-dup stdout-isolation trick
from `civex_plugin_sdk.io.isolate_stdout()` (CIVEX-133) is done in
`entrypoint.sh` instead of in-process: it duplicates the real stdout fd to
fd 3 and redirects the public fd 1 to `/dev/null` *before* the JVM starts,
so `System.out.println` (from your own code or a library) can never
corrupt the protocol stream. `Main` writes every frame through
`/proc/self/fd/3`, never through `System.out`.

## Trying it locally

```sh
docker build -t java-plugin-starter .
echo '{"type":"describe"}' | docker run -i java-plugin-starter describe
echo '{"type":"run","inputs":{},"config":{"text":"hello"}}' \
  | docker run -i java-plugin-starter run
```

## Dependencies

`Main.java` hand-rolls its own minimal JSON encode/decode rather than
pulling in a library, so the whole plugin builds with nothing but a JDK —
no Maven/Gradle dependency resolution to keep reproducible or content-hash
for image caching. If your plugin needs a real dependency (a JSON library,
an HTTP client, ...), add a build tool of your choice to the `build` stage
of the Dockerfile.
