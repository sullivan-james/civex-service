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

- `Ctx.commit()` does nothing and warns (`DeprecationWarning`): the host
  keeps a run's writes when it ends, or none of them if a step fails.
- New `Ctx.patch_record(record_id, fields)`: change only these fields.
  `update_record`'s docstring now says it replaces the record's data.
- `capabilities` are permission actions (`read`, `write_records`,
  `manage_files`, `delete`), each granting every `Ctx` method needing it;
  single method names still work.
- `PROTOCOL_VERSION` is 2: a plugin may send `progress` frames.
  `Ctx.progress(done, total=None, message="")` says how far a run has got;
  the civex app shows it in the status bar. A host speaking 2 still runs
  plugins on 1.
- `print()` from a plugin is no longer thrown away: `serve()` and
  `serve_container()` replace `sys.stdout` and `sys.stderr` with
  `io.LogStream`, which sends each line as a `log` frame (`stream` says
  which; a half-written line before the run's answer).
- `FrameWriter.send` holds a lock, so frames sent from two threads never
  interleave.
- `parse_frame` reads a `describe_result` with no `protocol_version` as 1
  (it read the SDK's own version).

## v0.2.0 (2026-09-30)

First release published to PyPI (planned tag `sdk-v0.2.0`), under the MIT
license. Previously the SDK shipped only vendored inside the `civex` wheel.

- `table`/`bytes` IOSpec values cross the wire as a typed columnar/binary
  envelope (`civex_plugin_sdk.io_convert`); the `[table]` extra provides the
  pandas a `table`-typed plugin is handed.
- New `PROTOCOL_VERSION` (currently 1), carried in `DescribeResult` as
  `protocol_version`. Older SDKs omit it and are treated as version 1. The
  civex host refuses a plugin whose version it doesn't speak, with a message
  saying which side to upgrade.
