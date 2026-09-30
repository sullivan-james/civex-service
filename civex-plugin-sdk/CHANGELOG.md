# Changelog — civex-plugin-sdk

One section per published release, newest first, under a running
`## Unreleased` heading for work not yet tagged. The version is **not** written
anywhere in the repo: it comes from the `sdk-vX.Y.Z` git tag. To release,
rename `## Unreleased` to `## vX.Y.Z (YYYY-MM-DD)` (CI requires a dated entry
for the tag) and push the tag — see `docs/contributing/sdk-release.md` in the
civex repo. Any change under `src/` must also touch this file (CI enforces it).

Choose the version when you tag: minor for anything a plugin author or the
civex host could observe (wire format, IO conversion, public API), patch for
fixes that change neither. A change to the wire protocol itself also bumps
`PROTOCOL_VERSION` (see `civex_plugin_sdk.protocol`).

## Unreleased

First release published to PyPI (planned tag `sdk-v0.2.0`), under the MIT
license. Previously the SDK shipped only vendored inside the `civex` wheel.

- `table`/`bytes` IOSpec values cross the wire as a typed columnar/binary
  envelope (`civex_plugin_sdk.io_convert`); the `[table]` extra provides the
  pandas a `table`-typed plugin is handed.
- New `PROTOCOL_VERSION` (currently 1), carried in `DescribeResult` as
  `protocol_version`. Older SDKs omit it and are treated as version 1. The
  civex host refuses a plugin whose version it doesn't speak, with a message
  saying which side to upgrade.
