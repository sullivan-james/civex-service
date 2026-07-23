# R container-tier plugin starter

A minimal template for a Tier 2 (container) civex plugin written in R. It
implements the same newline-delimited JSON wire protocol as the Tier 1
subprocess SDK (`civex-plugin-sdk`) — `describe`/`run` frames over
stdin/stdout, plus the fd-dup stdout-isolation trick so stray R output can't
corrupt the protocol stream — so the host side needs no R-specific code to
drive it.

## Usage

1. Copy this directory to `_civex/plugins/<name>/` in your project.
2. Edit `civex-plugin.toml` and the `PLUGIN_*` constants at the top of
   `plugin.R` to declare your plugin's `id`/`name`/`category`/`capabilities`
   — keep the two in sync.
3. Replace `invoke()` in `plugin.R` with your plugin's own logic.
4. Add any R packages your logic needs to the `Dockerfile`.

## Files

| File | Purpose |
|---|---|
| `civex-plugin.toml` | Manifest: `id`/`name`/`category`/`capabilities` |
| `Dockerfile` | Builds the image; `docker run -i <image> <mode>` runs it |
| `entrypoint.sh` | fd-dup stdout isolation, then execs `Rscript plugin.R <mode>` |
| `plugin.R` | The shim: wire protocol I/O plus your `invoke()` |
