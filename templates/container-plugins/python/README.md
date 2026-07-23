# Python container-plugin starter

Copy this directory into `_civex/plugins/<name>/` to scaffold a new Tier 2
(container-tier) plugin:

```
_civex/plugins/<name>/
  civex-plugin.toml   # id/name/category/capabilities manifest
  Dockerfile           # builds the image civex runs
  plugin.py            # your plugin logic
```

1. Edit `plugin.py`: rename `Plugin.id`/`name`/`category`, declare
   `capabilities` and a `Config`, and implement `invoke()`.
2. Update `civex-plugin.toml` to match `Plugin.id`/`name`/`category`/
   `capabilities`.
3. Add any extra dependencies your plugin needs to the `Dockerfile`.

`civex_plugin_sdk.serve_container` handles the wire protocol (the same
newline-delimited JSON frames Tier 1 subprocess plugins speak, including the
fd-dup stdout isolation trick) -- you only need to write `invoke()`.
