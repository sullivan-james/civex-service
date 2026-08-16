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
3. **Bundles a civex-plugin-sdk wheel** (`uv build --wheel -o
   src/civex/_vendor/sdk civex-plugin-sdk`) — see "The plugin SDK is not
   published by `release.yml`" below.
4. **Builds the wheel** (`python -m build --wheel`), with the version
   resolved from the pushed tag via `setuptools-scm` as above.
5. **Creates a GitHub Release** attaching the wheel, with
   `generate_release_notes: true` for the auto-generated commit list
   alongside the hand-written `CHANGELOG.md` entry.
6. **Publishes to PyPI** via `pypa/gh-action-pypi-publish`, with
   `skip-existing: true` so a re-run against an already-published version
   doesn't fail the job.

## The plugin SDK is not published by `release.yml`

`civex-plugin-sdk` (`civex-plugin-sdk/`) has its own version in its own
`pyproject.toml` and is not built or published as its own PyPI project by
this workflow — pushing a `v*` tag releases `civex` only, and
`civex-plugin-sdk` is not on PyPI under its own name.

Until v1.0.5, `civex`'s own `pyproject.toml` listed `civex-plugin-sdk` as a
plain runtime dependency anyway. Since nothing on PyPI satisfies that name,
pip couldn't resolve it, and every `pip install`/`pipx install civex` since
v1.0.5 silently fell back to the last version that *did* resolve (v1.0.4)
rather than erroring — see the v1.0.6 `CHANGELOG.md` entry. As of v1.0.6,
`civex` instead bundles the SDK with itself, covering both places it's
needed:

- **`civex`'s own imports** (the host-side subprocess plugin runtime does
  `from civex_plugin_sdk.io import ...`) — the SDK's source is vendored
  directly into the `civex` wheel (`[tool.setuptools.packages.find]` /
  `[tool.setuptools.package-dir]` in `pyproject.toml`), so it's just part
  of the same install.
- **Plugin authors' code**, which runs in a *separate*
  `uv run --no-project` environment per plugin and needs `civex-plugin-sdk`
  resolvable there too. `subprocess_runtime.py` points `--find-links` at a
  directory holding a real `civex-plugin-sdk` wheel: a fresh one built from
  a sibling dev checkout when running out of this repo
  (`_find_sdk_source()`), otherwise the prebuilt wheel this install shipped
  as package data at `civex/_vendor/sdk/`
  (`_bundled_sdk_wheel_dir()`) — built by the release step above and never
  committed to the repo (see "Local build").

This is a stopgap, not the end state: it means every `civex` release
carries its own frozen copy of whatever SDK version was current at build
time, rather than plugin authors being able to depend on `civex-plugin-sdk`
independently, version it separately, or find it searchable on PyPI.
Publishing `civex-plugin-sdk` to PyPI as its own project (its own release
workflow, its own version tags, a license suited to third-party plugin
authors rather than civex's own PolyForm Shield license) is still separate,
not-yet-done work — once it's published, `_bundled_sdk_wheel_dir()` and the
package-data bundling step can both be deleted, since
`uv run --no-project` will resolve `civex-plugin-sdk` from the real index
with no override needed.

## Local build

To reproduce what CI does without pushing a tag (e.g. to sanity-check the
wheel contents):

```bash
cd frontend && npm ci && npm run build && cd ..
cp -r frontend/dist/. src/civex/server/static/
uv build --wheel -o src/civex/_vendor/sdk civex-plugin-sdk
pip install build
python -m build --wheel
```

The resolved version depends on your local tag/commit state exactly as it
would in CI — `setuptools-scm` reads it from `git describe`, not from any
file in the working tree.
