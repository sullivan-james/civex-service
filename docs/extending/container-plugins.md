# Container plugins

[Writing a plugin](writing-a-plugin.md) covers Tier 1: Python only, run via `uv run` as a subprocess. For a plugin that needs something the subprocess tier can't give — a different language, system binaries, GPU access, stricter resource limits — civex builds and runs it inside a Docker container instead: Tier 2. Both tiers speak the identical [wire protocol](wire-protocol.md) — the same `id`/`name`/`capabilities`/`Config`/`invoke()` shape, the same frame types — over `docker run -i <image> <mode>` rather than a persistent subprocess.

!!! warning "Tier 2 is not wired into workflow execution yet"

## The plugin directory

A container-tier plugin lives at `_civex/plugins/<name>/`, and is recognized as one (rather than a Tier 1 `.py` file) by the presence of both a `civex-plugin.toml` manifest and a `Dockerfile` in the same directory — that pairing is the whole marker; there's no separate registration step.

```
_civex/plugins/<name>/
  civex-plugin.toml   # id/name/category/capabilities manifest
  Dockerfile           # build context is this directory
  <source files>        # your plugin's implementation
```

### `civex-plugin.toml`

```toml
--8<-- "templates/container-plugins/python/civex-plugin.toml"
```

`id`/`name`/`category`/`capabilities` here must stay in sync with whatever your plugin's own `describe` response declares — the manifest is what a container-tier registry could read without building and running the image; the `describe` response (produced by actually running the built image in `describe` mode) is the same information, once the image exists, and is what a plugin-authoring surface (CLI, UI, AI authoring guide) would read in practice.

### The Dockerfile

The build context is the plugin's own directory — nothing outside it is visible to the build. Beyond that, it's an ordinary Dockerfile: install whatever runtime and dependencies your language needs, copy in your source, and set an `ENTRYPOINT` that ends up dispatching on `sys.argv[1]` / `os.Args[1]` / `argv[1]` (`describe` or `run`).

## The `docker run -i <image> <mode>` contract

The host runs your built image exactly like this — never anything more permissive:

```bash
echo '{"type":"describe"}' | docker run -i <image> describe
echo '{"type":"run","inputs":{...},"config":{...}}' | docker run -i <image> run
```

`<mode>` (the container's first argv) is `describe` or `run`. The container reads exactly one matching frame off stdin, does its work, writes exactly one response frame to stdout, and exits — one container process per operation, never a long-lived server. See [Two dispatch models](wire-protocol.md#two-dispatch-models) for why this differs from Tier 1's persistent process, and why it's actually useful here: a fresh container per call is what lets per-run `--memory`/`--cpus` limits and the timeout/kill wrapper apply cleanly to a single operation.

## Content-hash image caching

Building a Docker image on every workflow run would be far too slow, so civex never does — `ensure_image_built()` (`civex.plugins.container_build`) hashes every file in the plugin's directory (Dockerfile, source, manifest, keyed by relative path so the hash doesn't depend on directory walk order) and tags the built image with that hash: `civex-plugin-<safe-id>:<hash[:16]>`. The tag *is* the cache key — an unchanged directory resolves to a tag `docker image inspect` already finds locally, so `docker build` is skipped entirely, and `docker build` never runs twice for the same contents. Edit any file in the plugin's directory and the hash (and therefore the tag) changes, so the next run builds fresh automatically. This is the same idea `uv` already applies to Python venvs, applied to Docker images instead.

## One worked example per language

Every starter below implements the identical wire protocol — frame shapes, the `describe`/`run` dispatch on `argv[1]`, and the fd-dup stdout-isolation trick from [`isolate_stdout()`](wire-protocol.md#isolate_stdout-keeping-stray-output-off-the-wire) — so the host drives all of them with no per-language code.

### Python

Reuses `civex-plugin-sdk` directly — the same `Plugin`/`Ctx` classes Tier 1 uses, just served with `serve_container()` instead of `serve()`:

```python title="templates/container-plugins/python/plugin.py"
--8<-- "templates/container-plugins/python/plugin.py"
```

Starter: `templates/container-plugins/python/`.

### R

A hand-rolled shim (`plugin.R`, using `jsonlite`) implements the frame I/O and RPC round-trip directly; `entrypoint.sh` does the fd-dup isolation before `Rscript` starts, writing every protocol frame to `/dev/fd/3` rather than through R's own stdout.

Starter: `plugin-templates/r/`.

### Java

`Main.java` speaks the protocol directly (`id`/`name`/`capabilities`/`configSchema()`/`invoke()`). Since Java has no portable `dup2()`, the stdout-isolation trick is done in `entrypoint.sh` instead of in-process — `exec 3>&1; exec 1>/dev/null` before the JVM starts — and `Main` writes frames through `/proc/self/fd/3` rather than `System.out`.

Starter: `plugin-templates/java/`.

### Go

`shim.go` is the reusable protocol plumbing (frame I/O, the `Ctx` capability client, stdout isolation); `main.go` is the part you replace, implementing a small `Plugin` interface (`ID`/`Name`/`Description`/`Category`/`Capabilities`/`ConfigSchema`/`Invoke`).

Starter: `templates/plugins/go/`.

### Rust

Split into `protocol.rs` (frame shapes, mirroring `civex_plugin_sdk.protocol`), `io.rs` (fd-dup isolation + newline-delimited JSON I/O), `ctx.rs` (the `Ctx` capability client), and `plugin.rs` — the only file you edit, everything below its `Shim plumbing` marker stays as-is.

Starter: `plugin-starters/rust/`.

### C / C++

`src/shim.c` (protocol runtime: stdout isolation, frame I/O, `describe`/`run` dispatch, RPC calls) and `src/json.c` (a minimal dependency-free JSON value tree) are the plumbing; `src/plugin.c` is the example plugin you replace. Compiles with a C++ compiler unmodified, so a C++ plugin can reuse the same shim as-is.

Starter: `starters/c/`.
