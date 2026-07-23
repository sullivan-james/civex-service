# C / C++ plugin starter

A minimal, working Tier 2 (container) civex plugin written in C, plus the
protocol runtime (a "shim") it's built on. Speaks the same newline-delimited
JSON-over-stdio protocol as Tier 1 (`uv run`) plugins — see
`docs/writing-custom-plugins.md` for the protocol from the host's point of
view. C++ plugins can reuse `src/shim.c`/`src/json.c` as-is (compile them
with a C compiler, link from C++ — see "Using C++" below).

## Using this starter

1. Copy this whole directory into `_civex/plugins/<your_plugin_name>/` in
   your project.
2. Edit `civex-plugin.toml`: set `id`, `name`, `category`, `capabilities`.
3. Edit `src/plugin.c`: change the `ShimPlugin` descriptor (must match
   `civex-plugin.toml`) and `invoke()`'s body. `src/shim.c`/`src/json.c`
   are the protocol runtime — most plugins don't need to touch them.
4. The host builds `Dockerfile` and runs the image as
   `docker run -i <image> <mode>` (`<mode>` is `describe` or `run`); you
   don't invoke it directly in normal use.

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build: compiles the binary, copies it into a minimal runtime image. |
| `civex-plugin.toml` | Manifest (`id`/`name`/`category`/`capabilities`) the host reads to index the plugin without running the container. |
| `src/json.h`, `src/json.c` | Minimal JSON value tree: parser, serializer, accessors. No third-party dependency. |
| `src/shim.h`, `src/shim.c` | Protocol runtime: fd-dup stdout isolation, frame I/O, `describe`/`run` dispatch, RPC calls. |
| `src/plugin.c` | The example plugin itself (`invoke()` + its `ShimPlugin` descriptor) — this is what you edit. |

## The wire protocol

Newline-delimited JSON, one object per line, both directions over a single
stdin/stdout pair — no length prefix. Every line has a `"type"` field:

- Host → plugin: `{"type":"describe"}` or `{"type":"run","inputs":{...},"config":{...}}`.
- Plugin → host: `{"type":"describe_result",...}` or `{"type":"result","outputs":{...}}`
  or `{"type":"error","call_id":null,"error":{"kind":...,"message":...,"retryable":...}}`.
- Mid-`run`, either side can exchange `{"type":"rpc_call",...}` /
  `{"type":"rpc_result",...}` for a declared capability (`shim_rpc_call()` in
  `src/shim.c`) — strictly synchronous, no interleaving.

`<mode>` (the container's argv) picks which single frame the shim expects on
stdin: `describe` mode expects a `describe` frame and replies with
`describe_result`; `run` mode expects a `run` frame and replies with
`result` or `error`. The process handles exactly one top-level frame (plus
any RPC exchange nested inside a `run`) and exits — one process per
`docker run` invocation, same lifecycle Tier 1's `uv run <plugin>.py` has.

## The fd-dup stdout isolation trick

`isolate_stdout()` in `src/shim.c` runs before any plugin code, and does
exactly what Tier 1's `civex_plugin_sdk.io.isolate_stdout()` does in Python:
duplicates the real stdout fd (1) to a private fd, then redirects the
*public* fd 1 to `/dev/null`. Every protocol frame is written through the
private duped fd, never through fd 1. A plugin author's `printf()`s, or
noise from a linked library, go to `/dev/null` and can never interleave
with/corrupt the JSON on the wire. `src/plugin.c`'s example `invoke()`
deliberately `printf()`s a debug line to demonstrate this — pipe the
binary's stdout to a file and confirm only the JSON result line lands there.

## Building and testing locally

```bash
# From this directory:
gcc -O2 -Wall -Wextra -std=c11 -o plugin src/json.c src/shim.c src/plugin.c -lm

echo '{"type":"describe"}' | ./plugin describe
echo '{"type":"run","inputs":{"a":2,"b":3.5},"config":{}}' | ./plugin run
```

Or via Docker, exactly as the host will invoke it:

```bash
docker build -t c-example-sum .
echo '{"type":"describe"}' | docker run -i c-example-sum describe
echo '{"type":"run","inputs":{"a":2,"b":3.5},"config":{}}' | docker run -i c-example-sum run
```

## Using C++

`src/shim.c`/`src/json.c` are plain C11 and compile fine with a C++
compiler too. To write `plugin.c`'s logic in C++, rename it `plugin.cpp`,
wrap the `#include "shim.h"`/`#include "json.h"` lines aren't C++-specific
(no `extern "C"` needed — the headers use no C++ keywords), and update the
`gcc` invocations above (and `Dockerfile`) to `g++`/`clang++` with your
plugin's translation unit.
