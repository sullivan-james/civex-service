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

For anything sizeable, cut a release candidate first (see
[Pre-releases](#pre-releases)) and try it before tagging the final version.

## What `release.yml` does

Triggered on push of any `v*` tag. It runs three jobs, **build → test →
publish**, and the wheel that is published is the very file that was tested:
a PyPI version can never be uploaded again, even after it is deleted, and
tests run from a checkout can't see what the wheel is missing (the checkout
has every file).

**build**

1. **Checks the tag and its CHANGELOG entry** (`scripts/check_release_tag.py`,
   the one rule for a release tag): the tag is a valid `v<version>`, and
   `CHANGELOG.md` has an entry for it, failing before anything is built. A
   final release needs its own `## vX.Y.Z` heading; a pre-release may also
   use the final version's heading or `## Unreleased`. This is the
   enforcement mechanism behind the changelog discipline described in
   `CHANGELOG.md` and `PRODUCTION_READINESS.md` §4a.
2. **Builds the frontend** (`npm ci && npm run build` in `frontend/`) and
   copies `frontend/dist/` into `src/civex/server/static/` — the wheel
   ships the built frontend as package data
   (`[tool.setuptools.package-data]` includes `server/static/**`), so a
   `pip install civex` gets a working web UI with no separate
   frontend build step.
3. **Verifies the plugin SDK is published** — `civex` depends on
   `civex-plugin-sdk` as a normal dependency, so the in-repo SDK version
   must already be on PyPI (`scripts/check_sdk_sync.py require-published`),
   and civex's declared range must admit it, and the SDK's source must be unchanged since its tag. See
   [Releasing civex-plugin-sdk](sdk-release.md).
4. **Builds the wheel** (`python -m build --wheel`), with the version
   resolved from the pushed tag via `setuptools-scm` as above (only `v*` tags
   count; `sdk-v*` tags version the SDK and are ignored here), checks the
   wheel's version is the tag's, and keeps it as a workflow artifact.

**test**, on Linux, macOS and Windows

5. **Installs the wheel the way the install guide says**
   (`uv tool install`, with no Python set up: uv fetches one) and **runs it**
   with `scripts/smoke_civex.py`: `civex --version` must be the tag's
   version, then `init`, a schema, `serve`, the API and the bundled web UI.

**publish**, only if every test passed

6. **Publishes to PyPI** via `pypa/gh-action-pypi-publish`, with
   `skip-existing: true` so a re-run against an already-published version
   doesn't fail the job.
7. **Creates a GitHub Release** attaching the wheel, with
   `generate_release_notes: true` for the auto-generated commit list
   alongside the hand-written `CHANGELOG.md` entry, marked as a pre-release
   for a pre-release tag. It comes after PyPI so a release page never offers
   a version pip can't get.

`build-desktop.yml` runs on the same tags, builds the standalone apps, runs
the same smoke test on each, and attaches them to the same release (marked a
pre-release by the same rule).

## Pre-releases

Tag a release candidate to try a release on the real PyPI before it is final:

```bash
git tag v1.3.0rc1 && git push origin v1.3.0rc1
```

Any [PEP 440](https://peps.python.org/pep-0440/) pre-release works (`rcN`,
`bN`, `aN`, `.devN`). Its changelog entry can still be `## Unreleased`, or
already `## v1.3.0`; it doesn't need one of its own. It goes through the
same build, test and publish, and is marked a pre-release on GitHub, so
"latest" still points at the last final release.

Installers skip pre-releases unless asked, so nobody gets one by accident:

```bash
uv tool install --prerelease allow civex   # or: uv tool install civex==1.3.0rc1
civex update --pre                         # an existing install
```

When it's good, add the dated `## v1.3.0` entry and tag `v1.3.0`. Installs on
the candidate move to it with a plain `civex update`.

Don't use TestPyPI for this: civex's dependencies aren't there, so it only
works with real PyPI as an extra index, which tests a different resolution
from the one users get and can pick up a lookalike package from the other
index.

## The plugin SDK is released separately

`civex-plugin-sdk` is its own PyPI project with its own tag-derived version,
tag namespace (`sdk-v*`) and workflow (`release-sdk.yml`); pushing a `v*` tag
releases `civex` only. `civex` depends on it with a compatible-range
requirement, and `release.yml` refuses to publish unless the in-repo SDK
version is already on PyPI (this is what prevents a repeat of the v1.0.5
silent-fallback bug). The full model, guards and procedure are in
[Releasing civex-plugin-sdk](sdk-release.md).

Before v1.1.0 the SDK was vendored into the `civex` wheel and shipped as a
prebuilt wheel in package data; both are gone.

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

To try the wheel the way the release job does, install it into its own
environment (not your checkout's) and run the smoke test against it:

```bash
uv tool install --force ./dist/civex-*.whl
python scripts/smoke_civex.py "$(uv tool dir --bin)/civex"
```
