# Plugin starters

Prebuilt starter templates for Tier 2 (container) civex plugins, one
directory per language. Each starter is a minimal, working plugin
implementing the same stdin/stdout JSON protocol as Tier 1 (subprocess)
plugins — see `docs/writing-custom-plugins.md` for the protocol itself and
[c/README.md](c/README.md) for how to use a starter.

To scaffold a new plugin, copy the language directory you want into
`_civex/plugins/<your_plugin_name>/` in your project and edit it there.

| Language | Directory |
|---|---|
| C / C++ | [`c/`](c/) |
