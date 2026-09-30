# Changelog — civex-plugin-sdk

One section per published release: `## vX.Y.Z (YYYY-MM-DD)`. The version in
`pyproject.toml` is the source of truth and is bumped **by hand** whenever
anything under `src/` changes (CI enforces this — see
`docs/contributing/sdk-release.md` in the civex repo). An entry for the
current version must exist before its `sdk-vX.Y.Z` tag is pushed; the release
workflow refuses to publish without one.

Bump the minor version for anything a plugin author or the civex host could
observe (wire format, IO conversion, public API); the patch version for fixes
that change neither. A change to the wire protocol itself also bumps
`PROTOCOL_VERSION` (see `civex_plugin_sdk.protocol`).

## v0.2.0 (unreleased)

First release published to PyPI under the MIT license. Previously the SDK
shipped only vendored inside the `civex` wheel.

- `table`/`bytes` IOSpec values cross the wire as a typed columnar/binary
  envelope (`civex_plugin_sdk.io_convert`); the `[table]` extra provides the
  pandas a `table`-typed plugin is handed.
- New `PROTOCOL_VERSION` (currently 1), carried in `DescribeResult` as
  `protocol_version`. Older SDKs omit it and are treated as version 1. The
  civex host refuses a plugin whose version it doesn't speak, with a message
  saying which side to upgrade.
