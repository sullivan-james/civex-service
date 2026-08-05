# Contributing

Contributor docs — dev setup, architecture, testing, and the release process
— live under [`docs/contributing/`](docs/contributing/dev-setup.md), not in
this file. This is a short pointer, kept at the repo root because GitHub
surfaces `CONTRIBUTING.md` in the issue/PR UI automatically.

- [Dev setup](docs/contributing/dev-setup.md) — install, running the app locally, `make` targets
- [Architecture](docs/contributing/architecture.md) — module layout, layer rules, data model, plugin tiers
- [Testing](docs/contributing/testing.md) — test structure and coverage status
- [Release process](docs/contributing/release.md) — versioning, tagging, what `release.yml` does
- [Publishing the docs site](docs/contributing/publishing-docs.md) — how `docs/` gets built and deployed

Before opening a PR, run `make check` (mirrors CI) and `make pre-commit`
locally — see [Dev setup](docs/contributing/dev-setup.md) for the full list
of targets.
