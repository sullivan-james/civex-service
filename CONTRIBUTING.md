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

## Testing an unreleased civex in civex-hub

Every push to a branch of this repository builds a wheel (web app included) and publishes it as a GitHub prerelease tagged `dev-<sha12>` (workflow `dev-build.yml`). The version is `<next patch>.dev<commits since the last tag>`, e.g. `2.2.1.dev14`. These are not on PyPI, so `civex update` ignores them. Forks never publish.

```bash
scripts/dev_build_url.sh <branch-or-sha>   # prints "<wheel url> <sha256>"; exits 1 until the build is there
uv pip install "$(scripts/dev_build_url.sh my-branch | cut -d' ' -f1)"
```

civex-hub may depend on that URL directly (`civex @ https://github.com/sullivan-james/civex-service/releases/download/dev-<sha12>/<wheel>`). The downloads need no login.

A weekly job deletes dev builds older than 90 days. **Before a hub release, add the sha the hub pins to `dev-builds-keep.txt`** on `main`, or its build will eventually be pruned.
