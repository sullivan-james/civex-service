# Releasing civex-plugin-sdk

`civex-plugin-sdk` is its own PyPI project, released independently of `civex`
but developed in this repo (`civex-plugin-sdk/`). Plugin authors depend on it
directly (`dependencies = ["civex-plugin-sdk"]` in a PEP 723 header), and
`civex` depends on it like any other package. It is licensed **MIT**
(`civex-plugin-sdk/LICENSE`); the rest of the repo is PolyForm Shield. The
`civex` wheel no longer contains any SDK code, so the two licenses never mix
in one artifact.

## How the pieces fit

```
civex-plugin-sdk/pyproject.toml   version = "0.2.0"     <- hand-set, source of truth
        │  sdk-v0.2.0 tag  ─────────►  release-sdk.yml  ─────►  PyPI: civex-plugin-sdk
        │
pyproject.toml                    "civex-plugin-sdk>=0.2.0,<0.3"   <- civex's declared range
        │  v1.1.0 tag  ─────────────►  release.yml      ─────►  PyPI: civex
        ▼
host at runtime                   uv run --with civex-plugin-sdk==<installed version>
```

Three different numbers are in play. Don't conflate them:

| Number | Where | Changes when |
|---|---|---|
| **SDK version** | `civex-plugin-sdk/pyproject.toml` | Anything under `civex-plugin-sdk/src` changes. Bumped by hand. |
| **civex's SDK range** | `pyproject.toml` `dependencies` | You deliberately widen it to admit a new compatible SDK. |
| **`PROTOCOL_VERSION`** | `civex_plugin_sdk/protocol.py` | The wire protocol changes in a way an old peer can't cope with. |

civex itself is versioned from git tags (see [Release process](release.md));
the SDK is not, because its version must change on every code change — it is
part of the `uv` cache key that decides whether a plugin's environment
re-resolves.

## Versioning rules

- **Every change under `civex-plugin-sdk/src` bumps the version.** Minor
  (`0.2.0` → `0.3.0`) for anything a plugin author or the host can observe:
  wire format, IO conversion, public API. Patch (`0.2.0` → `0.2.1`) for fixes
  that change neither.
- Why it's mandatory: the host runs plugins with `uv run --with
  civex-plugin-sdk==<version>`. `uv` caches a per-script environment keyed on
  its requirements. If the SDK's behaviour changes but the version doesn't,
  plugins that already resolved keep the old SDK and silently disagree with
  the host about the wire format.
- **`PROTOCOL_VERSION` is separate.** Bump it only for a breaking wire change
  (removed/renamed frame or field, changed semantics). Additive fields with
  defaults and bug fixes don't need it. The plugin reports it in its
  `describe` answer; the host refuses a mismatch with a message naming which
  side to upgrade (`civex update` for a newer plugin, upgrade the plugin's SDK
  for an older one). SDKs that predate the field are read as version 1.
- Add an entry to `civex-plugin-sdk/CHANGELOG.md` for every version.

## Keeping civex and the SDK in step

civex declares a **compatible range** (`>=0.2.0,<0.3`), not an exact pin, so an
SDK patch release doesn't force a civex release. Guards enforce the rest, all
implemented in `scripts/check_sdk_sync.py` (run it locally the same way CI
does: `uv run --no-project --with packaging python scripts/check_sdk_sync.py
check`).

| Guard | Runs | Fails when |
|---|---|---|
| Range admits SDK | every CI run, both release workflows | the in-repo SDK version is outside civex's declared range |
| SDK changelog entry | every CI run, both release workflows | `civex-plugin-sdk/CHANGELOG.md` has no `## vX.Y.Z` for the current version |
| Version bumped | pull requests (`--base origin/<base>`) | anything under `civex-plugin-sdk/src` changed but the version didn't rise |
| Tag matches version | `release-sdk.yml` | the tag isn't `sdk-v<pyproject version>` |
| Not already published | `release-sdk.yml` | that SDK version is already on PyPI (re-publishing is an error, not a no-op) |
| Changelog dated | `release-sdk.yml` | the entry's heading still says "unreleased" |
| **SDK published first** | `release.yml` (civex) | the in-repo SDK version isn't on PyPI yet |
| SDK tests | CI and `release-sdk.yml` | `civex-plugin-sdk/tests` fails |
| Built wheel imports | `release-sdk.yml` | the built wheel doesn't install and import in a clean venv |

The last-but-three guard is the one that matters most. In v1.0.5 civex
declared a dependency that wasn't on PyPI, and pip silently installed the
previous release instead of erroring. Requiring the SDK to be published
before civex can be released rules that out.

## Releasing the SDK

1. Make the change under `civex-plugin-sdk/src` and bump `version` in
   `civex-plugin-sdk/pyproject.toml`.
2. Add `## vX.Y.Z (YYYY-MM-DD)` to `civex-plugin-sdk/CHANGELOG.md`. (The
   heading may say `(unreleased)` while the work is in flight; the release
   workflow refuses it, so date it when you tag.)
3. If the wire protocol changed incompatibly, bump `PROTOCOL_VERSION` and
   update the host's handling in `subprocess_runtime.check_protocol_version`.
4. If the new version falls outside civex's range, widen the range in
   `pyproject.toml` (this is a `civex` change, released separately).
5. Merge, then push the tag:

   ```bash
   git tag sdk-v0.2.1 && git push origin sdk-v0.2.1
   ```

   `release-sdk.yml` runs the guards and the SDK tests, builds an sdist and
   wheel, checks their metadata, smoke-tests the wheel in a clean venv,
   creates a GitHub release, and publishes to PyPI.

## Releasing civex

Unchanged (see [Release process](release.md)), with one extra ordering rule:
**if the release depends on an SDK version that isn't on PyPI yet, publish the
SDK first.** `release.yml` checks this and fails before building anything if
you forget.

## First release (one-time setup)

`civex-plugin-sdk` has never been published, and PyPI trusted publishing has
to be configured before the first tag:

1. On PyPI go to *Account settings → Publishing → Add a new pending
   publisher* and enter: project `civex-plugin-sdk`, this repository's owner
   and name, workflow `release-sdk.yml`, environment left blank. No API token
   is stored anywhere.
2. Change `## v0.2.0 (unreleased)` in `civex-plugin-sdk/CHANGELOG.md` to
   today's date.
3. Push `sdk-v0.2.0`.
4. Only then tag the next civex release.

## Working on the SDK locally

In a checkout of this repo, `uv sync` installs the SDK from the workspace
(`[tool.uv.sources]`), so edits are live for `civex` and the tests. When the
host launches a plugin from a checkout it also builds a fresh wheel from
`civex-plugin-sdk/` and passes it as `--find-links`, so plugin environments
resolve the SDK you're editing rather than PyPI's — the version is pinned to
that wheel's. In a real install there is no sibling source, the SDK comes
from PyPI, and the host pins `civex-plugin-sdk==<the version civex itself
imports>`.

## If a bad SDK version ships

PyPI versions can't be replaced. Yank the release on PyPI (installers then skip
it unless pinned to it exactly), fix forward with the next patch version, and
note it in the changelog. If civex's range admits the bad version and can't
avoid it, narrow the range in a civex patch release.
