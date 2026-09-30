# Releasing civex-plugin-sdk

`civex-plugin-sdk` is its own PyPI project, released independently of `civex`
but developed in this repo (`civex-plugin-sdk/`). Plugin authors depend on it
directly (`dependencies = ["civex-plugin-sdk"]` in a PEP 723 header), and
`civex` depends on it like any other package. It is licensed **MIT**
(`civex-plugin-sdk/LICENSE`); the rest of the repo is PolyForm Shield. The
`civex` wheel contains no SDK code, so the two licenses never mix in one
artifact.

## Versions come from git tags

Neither package has a version written in its `pyproject.toml`. Both use
`setuptools-scm`, each with its own tag namespace:

| Package | Tag | Configured in |
|---|---|---|
| `civex` | `vX.Y.Z` | `pyproject.toml` (`[tool.setuptools_scm]`, matches only `v*`) |
| `civex-plugin-sdk` | `sdk-vX.Y.Z` | `civex-plugin-sdk/pyproject.toml` (matches only `sdk-v*`, `root = ".."`) |

How the pieces connect:

- Pushing an `sdk-vX.Y.Z` tag runs `release-sdk.yml`, which publishes
  `civex-plugin-sdk` X.Y.Z to PyPI.
- Pushing a `vA.B.C` tag runs `release.yml`, which publishes `civex` A.B.C.
- The civex package declares `civex-plugin-sdk>=X.Y,<X.(Y+1)` — the one SDK
  number written down anywhere.
- At runtime the host launches each plugin with
  `uv run --with civex-plugin-sdk==<the version it imports itself>`.

- A build **on** a tag is exactly that version (`sdk-v0.2.0` → `0.2.0`).
- A build **after** a tag is `X.Y.Z.postN` (N commits later), so development
  builds never collide with a release and sort between it and the next.
- The tag *is* the version, so there is nothing to bump in a file and nothing
  that can disagree with what was published.
- Anything that installs the project from git needs **tags fetched**. In CI
  that means `actions/checkout` with `fetch-depth: 0`; locally,
  `git fetch --tags`. Without a reachable `sdk-v*` tag the SDK reads as
  `0.0.postN` and civex's range rejects it.

Three numbers are in play — don't conflate them:

| Number | Where | Changes when |
|---|---|---|
| **SDK version** | `sdk-v*` tag | You tag a release. |
| **civex's SDK range** | `pyproject.toml` `dependencies` | You deliberately widen it to admit a new compatible SDK. |
| **`PROTOCOL_VERSION`** | `civex_plugin_sdk/protocol.py` | The wire protocol changes in a way an old peer can't cope with. |

## Choosing a version

Pick it when you tag. Minor (`0.2.x` → `0.3.0`) for anything a plugin author or
the host can observe: wire format, IO conversion, public API. Patch for fixes
that change neither.

`PROTOCOL_VERSION` is separate. Bump it only for a breaking wire change
(removed/renamed frame or field, changed semantics); additive fields with
defaults and bug fixes don't need it. The plugin reports it in its `describe`
answer and the host refuses a mismatch with a message naming which side to
upgrade (`civex update` for a newer plugin; upgrade the plugin's SDK for an
older one). SDKs that predate the field are read as version 1.

The host pins `--with civex-plugin-sdk==<version>` when it runs a plugin.
`uv` caches a per-script environment keyed on its requirements, so a new SDK
release makes plugins re-resolve rather than keep an old SDK that disagrees
with the host about the wire format.

## Keeping civex and the SDK in step

civex declares a **compatible range** (e.g. `>=0.2,<0.3`), not an exact pin, so
an SDK patch release doesn't force a civex release. Guards enforce the rest,
all in `scripts/check_sdk_sync.py` ("the SDK version" below means the newest
`sdk-v*` tag reachable from HEAD). Run it locally the way CI does:
`uv run --no-project --with packaging python scripts/check_sdk_sync.py check`.

| Guard | Runs | Fails when |
|---|---|---|
| Range admits SDK | every CI run, both release workflows | civex's declared range excludes the SDK version |
| SDK change has a changelog entry | pull requests (`--base`) | anything under `civex-plugin-sdk/src` changed but `civex-plugin-sdk/CHANGELOG.md` didn't |
| Valid, newer tag | `release-sdk.yml` | the tag isn't `sdk-vX.Y.Z`, or isn't newer than everything on PyPI (a typo can't publish out of order) |
| Not already published | `release-sdk.yml` | that version is already on PyPI (re-publishing is an error, not a no-op) |
| Dated changelog entry | `release-sdk.yml` | no `## vX.Y.Z (YYYY-MM-DD)` heading for the tag, or it still says "unreleased" |
| **SDK published first** | `release.yml` (civex) | the SDK version isn't on PyPI yet |
| **No unreleased SDK changes** | `release.yml` (civex) | `civex-plugin-sdk/src` changed since the newest `sdk-v*` tag, so the published SDK isn't the one civex was built against |
| SDK tests | CI and `release-sdk.yml` | `civex-plugin-sdk/tests` fails |
| Built wheel imports | `release-sdk.yml` | the built wheel doesn't install and import in a clean venv |

The two bold guards matter most. In v1.0.5 civex declared a dependency that
wasn't on PyPI, and pip silently installed the previous release instead of
erroring. Requiring the SDK to be published — and unchanged since — before
civex can be released rules that out.

## Releasing the SDK

1. Make the change under `civex-plugin-sdk/src` and describe it under
   `## Unreleased` in `civex-plugin-sdk/CHANGELOG.md` (CI requires the entry).
2. If the wire protocol changed incompatibly, bump `PROTOCOL_VERSION` and
   update the host's handling in `subprocess_runtime.check_protocol_version`.
3. If the version you're about to tag falls outside civex's range, widen the
   range in `pyproject.toml` (a `civex` change, released separately).
4. Merge. Then rename `## Unreleased` to `## vX.Y.Z (YYYY-MM-DD)`, merge that,
   and push the tag on that commit:

   ```bash
   git tag sdk-vX.Y.Z && git push origin sdk-vX.Y.Z
   ```

   `release-sdk.yml` runs the guards and the SDK tests, builds an sdist and
   wheel, checks their metadata, smoke-tests the wheel in a clean venv,
   creates a GitHub release, and publishes to PyPI.

## Releasing civex

Unchanged (see [Release process](release.md)), with one ordering rule: **if the
release depends on SDK changes that aren't tagged and published yet, release
the SDK first.** `release.yml` checks this and fails before building anything.

## First release (one-time setup)

`civex-plugin-sdk` has never been published, and there is no `sdk-v*` tag yet.
Until one exists, an install from git can't satisfy civex's range. So the
first tag has to come *before* anything else that installs the project:

1. On PyPI go to *Account settings → Publishing → Add a new pending
   publisher* and enter: project `civex-plugin-sdk`, this repository's owner
   and name, workflow `release-sdk.yml`, environment left blank. No API token
   is stored anywhere.
2. On the branch that adds this setup, rename `## Unreleased` in
   `civex-plugin-sdk/CHANGELOG.md` to `## v0.2.0 (YYYY-MM-DD)`.
3. Push the branch, then tag its tip and push the tag:
   `git tag sdk-v0.2.0 && git push origin sdk-v0.2.0`. The workflow runs from
   the tagged commit and publishes `0.2.0`.
4. CI on the pull request can now find the tag (it is an ancestor of the merge
   commit) and passes. Merge.
5. Only then tag the next civex release.

## Working on the SDK locally

In a checkout, `uv sync` installs the SDK from the workspace
(`[tool.uv.sources]`), so edits are live for `civex` and the tests; its version
is the newest tag plus `.postN`. When the host launches a plugin from a
checkout it also builds a fresh wheel from `civex-plugin-sdk/` and passes it as
`--find-links`, so plugin environments resolve the SDK you're editing rather
than PyPI's, pinned to that wheel's version. In a real install there is no
sibling source, the SDK comes from PyPI, and the host pins
`civex-plugin-sdk==<the version civex itself imports>`.

If `uv sync` complains that `civex-plugin-sdk 0.0.postN` doesn't satisfy the
range, your clone has no `sdk-v*` tag: `git fetch --tags`.

## Upgrading from civex 1.0.6 or earlier

Those releases vendored the SDK inside the `civex` wheel. When pip upgrades
across that change it installs the SDK dependency first, then uninstalls the
old civex, whose file list still names `civex_plugin_sdk/*` — so it deletes the
SDK it just installed. The metadata survives (`pip check` is clean) but
`import civex_plugin_sdk` fails.

`civex/_sdk_repair.py` handles this: on `import civex`, if the SDK's metadata
is present but the module is missing, it force-reinstalls that same version
with `--no-deps` (pip, falling back to `uv pip`) and prints one line to stderr.
It never raises; on failure it prints the manual command. Fresh installs and
later upgrades never match that signature, so the check costs one
`find_spec` call. This can be deleted once nobody is plausibly still on
civex 1.0.6 or earlier.

## If a bad SDK version ships

PyPI versions can't be replaced. Yank the release on PyPI (installers then skip
it unless pinned to it exactly), fix forward with the next version, and note it
in the changelog. If civex's range admits the bad version and can't avoid it,
narrow the range in a civex patch release.
