# Go starter template (Tier 2 / container plugin)

Copy this whole directory into `_civex/plugins/<name>/` to start a new
Go-based container plugin:

```
_civex/plugins/<name>/
  civex-plugin.toml   # id/name/category/capabilities
  Dockerfile
  go.mod
  shim.go             # wire protocol plumbing -- copy as-is, don't edit
  main.go             # your plugin logic -- replace the example
```

Then:

1. Edit `civex-plugin.toml` with your plugin's real `id`/`name`/`category`/
   `capabilities`.
2. Replace the example `computeDurationPlugin` in `main.go` with your own
   type implementing the `Plugin` interface declared in `shim.go`
   (`ID`/`Name`/`Description`/`Category`/`Capabilities`/`ConfigSchema`/
   `Invoke`), and update `civex-plugin.toml` to match.
3. Add any extra dependencies to `go.mod` (`go get ...`) -- the `Dockerfile`
   already runs `go build` against whatever `go.mod` declares.

civex builds and content-hash-caches the image from this directory itself;
there's no manual `docker build` step.

## Protocol

`shim.go` speaks the same newline-delimited JSON protocol over stdin/stdout
as the Python SDK (`civex-plugin-sdk`) used by Tier 1 subprocess plugins --
same frame shapes, same `Ctx` capability surface, same fd-dup trick to keep
a stray `fmt.Println` from corrupting the protocol stream. The one
structural difference: a container is invoked once per operation as
`docker run -i <image> <mode>` (`describe` or `run`, `os.Args[1]`), rather
than staying alive to field either frame type the way a long-lived `uv run`
subprocess does.

See `docs/extending/writing-a-plugin.md` in the main civex repo for the full
`Ctx` API reference -- every method there has a same-named, same-shaped
counterpart on the `*Ctx` in `shim.go`.
