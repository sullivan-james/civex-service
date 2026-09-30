# Changelog

One section per tagged release: `## vX.Y.Z — <label> (YYYY-MM-DD)`. Every
`v*` tag must have a matching entry here *before* the tag is pushed —
`.github/workflows/release.yml` fails the release job if it's missing (see
PRODUCTION_READINESS.md §4a). The version itself has one source of truth,
the git tag (resolved via setuptools-scm into `civex.__version__`); this
file is release notes, not a second place to track the number.

Within a release, put breaking or migration-relevant changes under their
own `### Breaking` heading first — schema/DB migration changes (see
PRODUCTION_READINESS.md item 1) always belong there, even when handled
automatically, since that's what someone upgrading needs to scan for.

v0.0.1 through v1.0.3 were tagged and released without this discipline in
place. Rather than leave the changelog's most recent entry frozen at
v0.0.3 while nineteen undocumented tags shipped past it on PyPI, v1.0.4
below is a single retroactively-written entry consolidating everything
that shipped across that whole range — not nineteen fabricated
per-tag entries reconstructed after the fact. Discipline applies starting
from the next tag forward.

## v1.1.0 — batteries included, `civex update` (2026-09-30)

### Breaking
- The `server`, `workflows`, `postgres`, `ai` and `telemetry` extras are now
  installed by default: a plain `pipx install civex` gives you the HTTP API
  and web UI, workflow execution and built-in plugins (pandas), the
  PostgreSQL driver, AI-assisted commands and the telemetry SDK.
  - The old extras remain as empty aliases, so `pip install "civex[server]"`
    and existing pipx installs keep resolving — no action needed.
  - Installs are larger (pandas/numpy alone add tens of MB), and
    `psycopg2-binary` is now required everywhere; on platforms without a
    prebuilt wheel it needs libpq to build.
  - `desktop` (pywebview) deliberately stays optional:
    `pipx install "civex[desktop]"`.
- New base dependencies: `packaging` and `civex-plugin-sdk` (`>=0.2.0,<0.3`).
  The SDK is now published to PyPI as its own MIT-licensed project instead of
  being vendored into the `civex` wheel; the bundled `_vendor/sdk` wheel and
  `civex_plugin_sdk` source copy are gone from the wheel. Publish the SDK
  (tag `sdk-v0.2.0`) before tagging this release — `release.yml` checks.
  - Upgrading from civex 1.0.6 or earlier: those releases shipped the SDK
    inside the civex wheel, and pip deletes the new SDK's files when it
    uninstalls the old civex. civex detects this on its first run after the
    upgrade and restores the SDK automatically (one stderr line, needs
    network access to PyPI or pip's cache). If that fails it prints the exact
    manual command: `pip install --force-reinstall --no-deps civex-plugin-sdk`.

### Features
- `civex update` upgrades an installed civex to the latest PyPI release. It
  detects pipx, `uv tool` or pip and runs the matching upgrade, refuses on
  editable dev installs, and verifies the installed version actually changed
  afterwards — pip can exit 0 while leaving the old version in place when a
  newer release's dependencies won't resolve (the v1.0.5 failure mode).
  `civex update --check` only reports.
- Records now include `reference_labels`: each reference/reference_list
  value's target `natural_name`, resolved in one batched query. The UI
  renders references as links with readable labels.
- Workflow, plugin and container-plugin editors are now routed pages
  (`/workflows/new`, `/plugins/:stem/edit`, …) instead of modals, and the
  import wizard is split into per-step components with a
  `/schemas/:id/import` entry point.

- The host now checks a plugin's wire `protocol_version` at describe time
  and refuses a mismatch with a message naming the side to upgrade, rather
  than failing opaquely mid-run. Plugins from SDKs that predate the field are
  read as version 1, so existing plugins keep working.
- CI now runs the SDK's own tests and guards that keep civex and the SDK in
  step (`scripts/check_sdk_sync.py`); the SDK has its own release workflow
  and its version comes from `sdk-v*` git tags, not from `pyproject.toml`.
  CI jobs that install the project now fetch full git history (tags).
  See `docs/contributing/sdk-release.md`.

### Fixes
- 4xx API errors are no longer retried by the UI, and a record that 404s
  stops polling, so "not found" pages render immediately instead of after
  ~7s of backoff.

## v1.0.6 — packaging fix (2026-08-16)

### Fixes
- `civex-plugin-sdk` was declared as a hard runtime dependency of `civex`
  in `pyproject.toml`, but was never published to PyPI in its own right.
  Since pip cannot resolve a nonexistent dependency, every
  `pip install civex` / `pipx install civex` since v1.0.5 shipped silently
  fell back to the last version that *did* resolve (v1.0.4) instead of
  installing the version actually requested, with no error shown. Fixed by
  bundling `civex-plugin-sdk` with `civex` itself instead of depending on it
  externally: its source is vendored directly into the `civex` wheel
  (`[tool.setuptools.packages.find]` / `[tool.setuptools.package-dir]` in
  `pyproject.toml`) for `civex`'s own imports, and a prebuilt SDK wheel now
  ships as package data at `civex/_vendor/sdk/` so subprocess-tier (Tier 1)
  plugins — which run in their own separate `uv run --no-project`
  environment per plugin — can resolve `civex-plugin-sdk` from this install
  instead of needing it on PyPI or a sibling dev checkout
  (`subprocess_runtime.py`'s `_bundled_sdk_wheel_dir()`).

### Known limitation
- This is a stopgap, not the real fix: every `civex` release now carries
  its own frozen copy of whatever SDK version was current at build time,
  rather than plugin authors being able to depend on `civex-plugin-sdk`
  independently or find it on PyPI. Publishing `civex-plugin-sdk` to PyPI
  as its own project is still separate, not-yet-done work. See
  [`docs/contributing/release.md`](contributing/release.md).

## v1.0.5 (2026-08-16)

### Breaking
- Schema and field `name`s are now slug-validated on create/rename
  (`^[a-z_][a-z0-9_]*$`); a new, optional `label` carries the free-text
  display name instead. Existing names created before this change keep
  working — `civex schema lint` reports any that don't conform.

### Features
- **Views** — save a column/filter/sort selection against a schema as a
  named view (web UI: column picker, AND/OR filter builder, live
  preview); export as CSV/JSON via the web UI or `civex view export`,
  with any file/file_list columns bundled into a zip. Columns can join
  one hop through a `reference` field (e.g. `customer.email`). A
  top-level **Views** page lists every saved view across all schemas,
  and a **Views** button on a collection's record list jumps to the
  views for whichever schema is currently filtered.
- **Analytics dashboard** — filterable, time-bucketed charts for data &
  schema growth, workflow reliability, AI usage, and the activity/audit
  trail, behind a shared URL-synced filter bar.
- **Advanced record filtering** — multi-operator, AND/OR grouped filters
  for record queries (web UI and API), plus a reusable search picker for
  reference-field and parent-record selection.
- **Soft-delete everywhere** — schemas, collections, and records now move
  to Recently Deleted instead of being removed outright, with restore and
  a typed-confirmation + blast-radius warning before cascading deletes.
- **Filename templates** — a `filename_template` restriction on
  `file`/`file_list` fields resolves a per-record download name from
  other field values; reflected in the record API's `resolved_filename`,
  single-file downloads, and bulk zip export.
- **Guided import wizard** — import a folder of files or a spreadsheet
  into a collection through a step-by-step wizard.
- **Change history everywhere** — schema and record detail pages show a
  collapsible change history; the audit log is also exposed via HTTP API.
- **Tier 2 container plugins** — `docker run` execution with memory/CPU
  limits and a timeout/kill wrapper, plus starter Dockerfiles + language
  shims for Go, Python, Rust, R, Java, and C/C++.
- Workflow YAML editor now autocompletes plugin ids, config keys, and
  step output references.
- Navigation restructured around researcher tasks (Collections, Views,
  Schemas, Workflows, Runs, Analytics) instead of raw database tables;
  Runs rebuilt as a readable audit trail.

### Other
- Internal data-model hardening, applied automatically via Alembic on
  upgrade: composite FK enforcing record parent/dataset consistency,
  normalized `workflow_jobs.step_executions`, referential integrity for
  `display_field`, and a `search_vector` trigger fix.
- Dark mode via token overrides; hardcoded color literals swept from the
  frontend and lint-blocked going forward.
- Broad frontend UI-primitive consolidation (Page template, Field/Input/
  Select/Checkbox, ConfirmDialog, Modal, Toast, IconButton, DataTable)
  applied across every route, plus aria-live regions and dialog semantics
  for sync/job/empty states and panels.

### Installation
See [README.md](README.md) for `pipx` install instructions.

## v1.0.4 (2026-07-16)

Consolidated summary of everything shipped since the original v0.0.3
alpha release (see `git log v0.0.3..v1.0.4` for the raw commit history).
Despite the version number, this is still an alpha release — see
PRODUCTION_READINESS.md for what's blocking a real 1.0.

### Breaking
- `civex dataset` CLI command renamed to `civex collection` (underlying
  service/module names are unchanged; update any scripts that call
  `civex dataset ...` directly).
- License changed from the original "Civex Freeware License" to a new
  "Civex Software License Agreement" — review terms before upgrading.

### Features
- **AI assistant** — `civex ai` configures a provider (Anthropic, Groq,
  Gemini, Ollama, or any OpenAI-compatible endpoint); a chat panel in the
  web UI can inspect and act on schemas/datasets/records via tool calls.
- **Desktop app** — `civex-desktop` packages civex as a native tray
  application (PyInstaller, cross-platform builds attached to GitHub
  releases), with open/recent-project UI and local file logging.
- **Database migrations** — Alembic-managed schema migrations
  (`src/civex/db/migrations/`), applied automatically on connect;
  `civex db current` / `civex db migrate` for manual control.
- **Structured logging & telemetry** — structlog-based JSON logging with
  secret redaction, and opt-in Sentry error telemetry.
- **Local server hardening** — `LocalGuardMiddleware` adds DNS-rebinding
  and CSRF defenses to the loopback-only dev server.
- **CivexHub remote sync** — SSH transport, multi-volume support, and UI
  parity for pushing/pulling to a bare civex repository. (CivexHub was
  later split out of this repo entirely — see CIVEX-13 — so this is the
  last entry here that touches it.)

### Fixes
- Creating a schema with a duplicate name no longer fails incorrectly.
- Plugin/workflow restore silently returning 0 on Windows.
- Various remote sync fixes.
- Terminal router now guarded behind a Unix platform check (it didn't
  work on Windows).
- Frontend build reliability in CI (esbuild `ETXTBSY` on Linux, a
  cross-platform shell for the build step).

### Other
- Expanded automated test suite (~32% coverage, CI-gated at 30% — see
  `docs/contributing/testing.md`).

### Installation
See [README.md](README.md) for `pipx` install instructions.
