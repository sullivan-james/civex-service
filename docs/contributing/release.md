# Release process

## Versioning

civex's version has one source of truth: the git tag. There is no version
string hand-maintained in `pyproject.toml` — `dynamic = ["version"]` is set
there, and `setuptools-scm` resolves the version from the most recent
`v`-prefixed tag (`v1.2.3`) into `civex.__version__` at build time.

```toml
[tool.setuptools_scm]
version_scheme = "post-release"
local_scheme = "no-local-version"
```

- `version_scheme = "post-release"` — a commit after a tag but before the
  next one gets a `.postN` suffix (`v1.2.3.post4`) rather than guessing at
  the next version number.
- `local_scheme = "no-local-version"` — no `+<git-sha>` local segment is
  appended. Local segments aren't valid on PyPI, and stripping them keeps
  the resolved version PEP 440-clean without extra config on the publish
  side.

## Cutting a release

1. Add a `## vX.Y.Z — <label> (YYYY-MM-DD)` section to `CHANGELOG.md` at the
   repo root, above the previous entry. Breaking or migration-relevant
   changes go under their own `### Breaking` heading first, so they're the
   first thing an upgrader sees.
2. Push a `v`-prefixed tag matching that heading (`git tag v1.2.3 && git
   push origin v1.2.3`). Pushing the tag is what triggers `release.yml`.

## What `release.yml` does

Triggered on push of any `v*` tag:

1. **Verifies a CHANGELOG entry exists for the tag** — greps `CHANGELOG.md`
   for a `## ${TAG}` heading and fails the job immediately if it's missing,
   before anything is built. This is the enforcement mechanism behind the
   changelog discipline described in `CHANGELOG.md` and
   `PRODUCTION_READINESS.md` §4a — a tag with no matching entry can't
   produce a release.
2. **Builds the frontend** (`npm ci && npm run build` in `frontend/`) and
   copies `frontend/dist/` into `src/civex/server/static/` — the wheel
   ships the built frontend as package data
   (`[tool.setuptools.package-data]` includes `server/static/**`), so a
   `pip install civex[server]` gets a working web UI with no separate
   frontend build step.
3. **Builds the wheel** (`python -m build --wheel`), with the version
   resolved from the pushed tag via `setuptools-scm` as above.
4. **Creates a GitHub Release** attaching the wheel, with
   `generate_release_notes: true` for the auto-generated commit list
   alongside the hand-written `CHANGELOG.md` entry.
5. **Publishes to PyPI** via `pypa/gh-action-pypi-publish`, with
   `skip-existing: true` so a re-run against an already-published version
   doesn't fail the job.

## The plugin SDK is not published by `release.yml`

`civex-plugin-sdk` (`civex-plugin-sdk/`) has its own version in its own
`pyproject.toml` and is not built or published by this workflow — pushing a
`v*` tag releases `civex` only. The SDK currently reaches plugin authors
only via the host's `uv build` into a scratch `--find-links` directory at
runtime (see `subprocess_runtime.py`); it is not on PyPI. Publishing it
independently, if and when it needs to be installable outside a civex
checkout, is a separate piece of work.

## Local build

To reproduce what CI does without pushing a tag (e.g. to sanity-check the
wheel contents):

```bash
cd frontend && npm ci && npm run build && cd ..
cp -r frontend/dist/. src/civex/server/static/
pip install build
python -m build --wheel
```

The resolved version depends on your local tag/commit state exactly as it
would in CI — `setuptools-scm` reads it from `git describe`, not from any
file in the working tree.
