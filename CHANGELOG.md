# Changelog

## v0.0.3 — Alpha (2026-06-17)

First alpha release.

### Features
- **Schema management** — create schemas with typed fields and single-parent inheritance
- **Datasets & records** — named collections with arbitrary JSON data, full-text search, pagination, and filtering
- **File fields** — content-addressed file storage (SHA-256, git object layout)
- **Workflow engine** — YAML-defined pipelines with topological step execution and plugin system
- **Built-in plugins** — `load_file`, `load_csv`, `get_field`, `save_field`, `rows_to_records`
- **Custom plugins** — drop `.py` files into `.civex/plugins/` for auto-discovery
- **HTTP server & React UI** — `civex serve` starts a local web server with full CRUD UI, workflow editor, job queue, and import/export
- **Interactive shell** — `civex shell` (and Terminal tab in the UI) for prefix-free command entry
- **Remote sync** — push/pull to a bare civex repository over SSH
- **SQLite default, PostgreSQL optional** — JSONB and GIN indexes on PostgreSQL
- **Windows support** — SQLite path handling fixed; civex shell works cross-platform

### Installation
See [README.md](README.md) for `pipx` install instructions.
