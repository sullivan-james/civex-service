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

See [Install](https://docs.civex.dev/getting-started/install.html) for the desktop app, upgrading, and installing from source.

## 60-second example

```bash
civex init
civex schema create trial --description "A single experimental trial"
civex schema add-field trial subject --type string --required
civex collection create study-2024
civex record add --to study-2024 --schema trial
civex serve                          # open http://localhost:8000
```

Take the [five-minute tour](https://docs.civex.dev/getting-started/tour.html) for the full walkthrough, including workflows.

## Documentation

Full docs: **[docs.civex.dev](https://docs.civex.dev/)**

- **Getting started** — [install](https://docs.civex.dev/getting-started/install.html), [your first project](https://docs.civex.dev/getting-started/first-project.html), [five-minute tour](https://docs.civex.dev/getting-started/tour.html)
- **Guides** — [schemas & fields](https://docs.civex.dev/guides/schemas-and-fields.html), [collections & records](https://docs.civex.dev/guides/collections-and-records.html), [files](https://docs.civex.dev/guides/files.html), [workflows](https://docs.civex.dev/guides/workflows.html), [automation](https://docs.civex.dev/guides/automation.html), [server & web UI](https://docs.civex.dev/guides/server-and-web-ui.html), [remote sync & CivexHub](https://docs.civex.dev/guides/remote-sync.html), [PostgreSQL](https://docs.civex.dev/guides/postgresql.html), [logging & telemetry](https://docs.civex.dev/guides/logging-and-telemetry.html)
- **Reference** — [CLI reference](https://docs.civex.dev/cli-reference.html), [plugins](https://docs.civex.dev/plugins.html), [writing custom plugins](https://docs.civex.dev/writing-custom-plugins.html)
- **Contributing** — [architecture](https://docs.civex.dev/contributing/architecture.html), [dev setup](https://docs.civex.dev/contributing/dev-setup.html)

## Development

```bash
make install   # uv sync — sets up the venv and dependencies
make check     # everything CI runs: format, lint, typecheck, test, docs build
```

See [dev setup](https://docs.civex.dev/contributing/dev-setup.html) for the full local development workflow.

## License

civex is free to use for any purpose, including commercial use. Redistribution and modification are not permitted. See [LICENSE](LICENSE) for full terms.
