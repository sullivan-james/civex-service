# civex

A local-first, command-line research data management system. Define schemas, collect records into collections, attach files, and automate processing with workflows — all on your own machine, with an optional web UI and HTTP server.

```
Schema ──defines──▶ Record
                      │
                      ├── stored in ──▶ Collection
                      ├── has ──────▶ Files (content-addressed objects)
                      └── triggers ──▶ Workflow jobs
```

## Install

```bash
pipx install "civex[server,workflows]"
```

See [Install](docs/getting-started/install.md) for the desktop app, upgrading, and installing from source.

## 60-second example

```bash
civex init
civex schema create trial --description "A single experimental trial"
civex schema add-field trial subject --type string --required
civex collection create study-2024
civex record add --to study-2024 --schema trial
civex serve                          # open http://localhost:8000
```

Take the [five-minute tour](docs/getting-started/tour.md) for the full walkthrough, including workflows.

## Documentation

Full docs live in [`docs/`](docs/index.md) — run `make docs` to browse them locally with live reload.

- **Getting started** — [install](docs/getting-started/install.md), [your first project](docs/getting-started/first-project.md), [five-minute tour](docs/getting-started/tour.md)
- **Guides** — [schemas & fields](docs/guides/schemas-and-fields.md), [collections & records](docs/guides/collections-and-records.md), [files](docs/guides/files.md), [workflows](docs/guides/workflows.md), [automation](docs/guides/automation.md), [server & web UI](docs/guides/server-and-web-ui.md), [remote sync & CivexHub](docs/guides/remote-sync.md), [PostgreSQL](docs/guides/postgresql.md), [logging & telemetry](docs/guides/logging-and-telemetry.md)
- **Reference** — [CLI reference](docs/cli-reference.md), [plugins](docs/plugins.md), [writing custom plugins](docs/writing-custom-plugins.md), [plugin SDK](docs/extending/sdk-reference.md)
- **Contributing** — [architecture](docs/contributing/architecture.md), [dev setup](docs/contributing/dev-setup.md)

## Development

```bash
make install   # uv sync — sets up the venv and dependencies
make check     # everything CI runs: format, lint, typecheck, test, docs build
```

See [dev setup](docs/contributing/dev-setup.md) for the full local development workflow.

## License

civex is free to use for any purpose, including commercial use. Redistribution and modification are not permitted. See [LICENSE](LICENSE) for full terms.
