# Changelog

One section per tagged release: `## vX.Y.Z — <label> (YYYY-MM-DD)`. Every
`v*` tag must have a matching entry here *before* the tag is pushed —
`.github/workflows/release.yml` fails the release job if it's missing (see
PRODUCTION_READINESS.md §4a). A pre-release tag (`v1.3.0rc1`) may use the
final version's entry or `## Unreleased` instead of one of its own. The version itself has one source of truth,
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

## v2.0.0 — syncing between machines, updates from the app (2026-10-07)

### Breaking

- Migration `c9e1f4a7b3d2` adds the sync tables, indexes on `audit_log`, and
  `audit_log.apply_state`. It runs automatically; existing history is kept.

### Added

- **Sync with an authority** (`civex sync`, `civex clone`): a project can follow
  another civex over HTTP. Changes merge field by field; the authority's value
  wins a clash and yours is kept as a conflict you can take back. Retries are
  safe, and a dropped connection resumes. See the Syncing guide.
- **Sync runs by itself** while the server is up (and with `civex sync watch`):
  after changes, on an interval, backing off when the authority is unreachable.
  Settings → Sync connects, shows status, syncs now, pauses and settles
  conflicts; the status bar shows a failing or waiting sync.
- `civex sync authority enable` + `civex sync device invite` turn a server into an
  authority; remote hosts reach only `/api/sync/v1/`.
- **Devices join by invite and sign in with a key.** An invite works once and
  expires (24 hours by default). The device makes a key of its own, which never
  leaves it, and signs in for a session of a few minutes; a server that isn't the
  one it joined is refused before anything is sent. `civex sync connect --invite`,
  `civex sync device invite|list|cancel|revoke`; Settings → Sync. Adds the
  `cryptography` dependency and migration `a8c4e2f6b1d9`.
- `civex serve --sync-only` serves only the sync API, for an authority behind an
  HTTPS proxy. Devices connect over `https://` only (`http://` for this computer).
- Sync protocol 2. A device and the authority use the newest version both speak,
  and one that can't says which side to update.
- Invites start with `civex_inv_`, recognised by gitleaks and secret scanners.
- **Update from the app** (Settings → Updates, and a notice in the status bar
  when a newer version is out): civex closes, installs the new version and
  starts again, reopening the page. It works for the desktop app and for
  `civex serve` installed with uv, pipx or pip. `GET`/`POST /api/update`.
- **Pre-releases**: `civex update --pre`, and *Include pre-releases* on the
  Updates page, install release candidates; nobody gets one otherwise.
- **Size** in Settings → Appearance (80% to 125%), remembered by each window;
  in the desktop app ⌘/Ctrl with + − 0 change it too.

### Changed

- **The desktop app is a small launcher** (about 30 MB) that installs civex
  with its own `uv` the first time it starts, then keeps it up to date. It no
  longer contains civex, so it never needs downloading again for a new
  version. Custom plugins work in it without anything else installed.
- **The desktop app installs properly**: a Windows installer
  (`civex-<version>-windows-setup.exe`: Start menu, uninstaller, no administrator
  needed) and a macOS disk image with one app for Intel and Apple silicon
  Macs. Neither is signed yet; the install guide says how to open them.
- **The desktop app's civex can be a terminal command**: the Windows
  installer's *Add the civex command to PATH* (on by default; uninstalling
  removes it), or Settings → Updates → *Command line* on any system.
- The desktop app no longer opens a terminal window, keeps its logs in its own
  folder (AppData on Windows), and installs the civex it was released with.
  There is no `civex-desktop` command any more; `civex desktop` opens the
  window from a terminal.
- On Intel Macs civex uses `cryptography` 48, the last version with Intel macOS
  builds: newer ones could only be installed there by compiling Rust.
- Install with `uv tool install civex`, which needs no Python on the computer.

### Fixes

- **Updating stops, and starts again, the other servers running from the same
  copy**, after asking (the Updates page lists them; `civex update` asks). An
  update from the app used to fail half way while a `civex serve` from the same
  copy ran in a terminal (on Windows a file in use can't be replaced).
- **Including pre-releases no longer brings in pre-releases of everything civex
  depends on** (a beta pydantic, an alpha sentry-sdk): the version found is
  installed by name instead.
- **An update's outcome is shown only while it is news**, and **Dismiss**
  forgets it for good. An update that got civex to the new version is no longer
  called failed because the installer tripped over a file in use.
- **The desktop app keeps what its pages remember** (pins, recent items,
  dismissed notices, the pre-releases choice) from one opening to the next: its
  window no longer starts in private mode.

- **`civex update` in a terminal updates the desktop app's copy** (the `civex`
  command the app puts on PATH). It used to try pip, which that copy hasn't got.
  It now upgrades with the app's own uv and folders. On Windows it refuses while
  the app is open, and finishes the upgrade once the command has exited, in the
  same window.

- **The page froze after using the navigation drawer** (a narrow window, as
  the macOS desktop app often is): closing it left the rest of the page
  unclickable. It is handed back now.
- **The Windows desktop app had no project menu** (open, create, reveal the
  data folder) and no native folder picker: the page decided whether it was in
  the desktop app before the app had said so.
- **Reordering a schema's fields now appears in history.** It wrote no entry,
  so the new order was in the database but nowhere in the history (and would
  never have reached another device once sync exists). Each field that moved is
  recorded as an edit of that field.
- **Renaming or deleting a field now records the name templates it rewrites.**
  A schema's record-name template, or a file field's download-name template,
  that used the field was updated without an entry; each template changed is
  now an edit of its schema or field in history.
- **The desktop downloads couldn't create a project** (`civex init` failed: the
  database migrations were left out of the bundle). Every release is now
  installed and run on Linux, macOS and Windows before it is published.
- After `civex update` reinstalled missing packages for a uv install, later
  updates did nothing: the repair pinned the version (`==`).

A new test (`tests/services/test_audit_replay.py`) does everything a person can
do to schemas, fields, collections, views and records and checks that the last
history entry about each thing matches the database, so the next change that
forgets to write history fails it.

## v1.2.0 — uniqueness policies, recoverable fields, old sync removed (2026-10-05)

### Added

- **Uniqueness policies on schemas.** A schema can declare keys (combinations
  of its own fields) that no two live records may share, within the same
  parent record or, for a top-level record, the same collection. Records with
  a blank in a key's fields aren't held to it. Enforced wherever a record is
  written (form, CLI, import, workflows); a refusal names the existing record.
  A policy can't be added while records already break it. Restoring a record
  whose values were taken meanwhile is refused with the same explanation
  (the restore window offers to open the other record), and Restore all /
  Restore selected leave such records deleted and count them as held back.
  Workflow steps that skip a refused row add a `duplicates` output naming what
  each collided with. Schema page **Uniqueness** tab; CLI `civex schema
  add-unique | remove-unique | unique`; `PUT /schemas/{name}/unique-keys`;
  carried in dump/restore.

- History now records who made each change. Every new entry stores the
  operating-system user running civex (`civex.identity.local_actor`), shown as
  "by <name>" in an entry's detail and as the first column of Activity. It is what the machine reports, not a verified
  identity, and entries made before this release have none. `actor` is also
  returned by the audit HTTP API.

- **Deleting a field can be undone.** A removed field used to disappear, and
  the values records held for it were lost the next time each record was
  saved. It is now marked deleted instead: every record keeps its value, so
  **restoring the field brings the values back**. A record shows them under
  **Deleted fields** with when the field was deleted and a **Restore…**
  button; Activity (press **Deleted**) lists deleted fields beside deleted
  schemas, collections and records, and **Restore all** includes them. A
  field can't come back while its schema is deleted, or while another field
  has taken its name. CLI: `civex schema restore-field <schema> <field-id>`,
  and `civex trash list --kind field`. A deleted field is not purged by
  retention yet.
- **A bulk delete can be undone from its one line in Activity.** Deleting a
  record with children (a recording with 70 selections) is one line; it now
  has a **Restore** button, and the line's window has **Restore everything…**,
  which says how many records come back and restores them parent-first. Before,
  only the individual records could be restored, one at a time, and finding
  the parent among them was hard. `GET|POST /audit/restore-all` takes a
  `batch` to scope it to one bulk delete.
- **A delete no longer has to be undone as a whole.** Restoring a selection
  whose recording is deleted used to mean restoring the recording and all 70
  selections deleted with it; restoring a record always brought back every
  child deleted alongside it. Now: the restore window offers **Restore only
  this** (the selection and the recording it sits under, leaving the others
  deleted), **this and what was deleted with it**, or all of it; and a bulk
  delete's window lets you **tick the records** to bring back (**Restore N
  selected**), with **Choose which…** from its Restore button. CLI:
  `civex record restore <id> --only-this --with-parents`. API:
  `POST /records/{id}/restore?only_this=&with_parents=` and
  `POST /records/restore-selected`; the restore plan reports `parents_needed`.
- **Describing and undoing a bulk delete is fast.** Working out what "restore
  everything" would do took about 18 database queries per record (a recording
  with 70 selections: over 1,200 queries, with the window on a spinner) and
  restoring 13 per record. Both are now a handful of queries however many
  records there are.
- **Activity leads with who.** Each line now starts with **Who** (always shown,
  including for bulk changes), then what happened, then when.
- A record or schema page for something that was deleted now says when, and
  offers **Restore…** (for a record that went with its schema, the window
  offers the schema first). A deleted thing no longer links to a page that
  isn't there.
- History entries for records store values by **field id** instead of name,
  so an entry stays correct when a field is renamed (before, old entries kept
  the old name and showed it unlabelled). The API still shows names in
  `changes`; `old_data`/`new_data` are the stored snapshot, so a record's
  values in them are now keyed by id. A change to a field that has since been
  deleted says so (`deleted` on the change). Collection entries record
  `schema_ids` beside `schemas`.
- The HTTP API gains `deleted_fields` on records, `deleted` on audit changes,
  `schema_name`/`deleted_at` on restore plans, `fields` on the restore-all
  plan, and `GET|POST /schemas/{schema}/fields/{field_id}/restore[-plan]`.

### Fixes

- A custom plugin could keep failing with `did not find executable at ...
  \Temp\civex-plugin-...\python.exe` after the v1.1.4 fix, because `uv`
  reuses the environment it built for the plugin and that environment still
  pointed at a Python from the earlier failed run. `civex doctor` now finds
  cached plugin environments whose Python no longer exists, and
  `civex doctor --fix` removes them (`uv` rebuilds each on the plugin's next
  run, so it only costs a slower first run). The plugin error itself now says
  to run it.

### Breaking

- **The old push/pull sync is removed.** It had no server to talk to and no
  authentication, and a clone silently lost data (labels, name templates,
  defaults, views), so it is being replaced by a new design (CIVEX-305)
  rather than patched. Gone: `civex push`, `civex pull`, `civex clone`,
  `civex remote ...`, `civex auth ...`, `civex status`, `civex init --bare`,
  the five hidden plumbing commands (`transfer-pack`, `receive-pack`,
  `head-seq`, `get-object`, `put-object`), the Sync menu in the web UI and
  the `/api/remote/*` routes. Nothing local is affected. To move a project
  between machines now, use `civex dump` / `civex restore` and copy
  `_civex/objects/`.
- A `[remote]` table in `config.toml` is ignored and dropped the next time the
  config is saved.
- `commit_id` is gone from audit entries in the HTTP API (it was null until a
  push), and the `commits` table is removed.
- Files that exist only on a remote are no longer fetched on demand; there is
  no remote.

### Migration

- `a3d8f0b6c125` adds a nullable `schemas.unique_keys` JSON column (uniqueness
  policies). It runs automatically and changes nothing until a policy is
  added. Downgrading drops the policies.
- `b7f2c9a14d36` adds `fields.deleted_at` and replaces the one-name-per-schema
  rule with one among live fields. Existing fields are untouched. Downgrading
  deletes any deleted fields (a deleted field can share a name with a live
  one).
- `a9d3e5f1c708` drops `commits` and `audit_log.commit_id`, and adds the
  columns the new sync will use to `audit_log` (`actor`, `device_id`, `hlc`,
  `hub_seq`, `sync_state`; only `actor` is written so far). Every history entry is
  kept. `audit_log` is rebuilt once, which can take a moment on a project with
  a very long history. Downgrading recreates an empty `commits` table.

## v1.1.4 — Windows plugin fix, install checks (2026-10-04)

### Fixes

- Custom plugins failed on Windows with `did not find executable at
  ...\Temp\civex-plugin-...\Python\...\python.exe` when Python came from the
  Python install manager. Plugins run with a restricted environment that left
  out `LOCALAPPDATA`, so `uv` looked for interpreters under the plugin's
  scratch folder. That variable (and `APPDATA`, `PROGRAMDATA`, `PROGRAMFILES`,
  `WINDIR`, `COMSPEC`, `PATHEXT`, `HOMEDRIVE`/`HOMEPATH`) is now passed
  through, as are `UV_PYTHON`, `UV_PYTHON_PREFERENCE`, `UV_NATIVE_TLS`, the
  proxy variables and `SSL_CERT_FILE`. Secrets such as the database URL and
  API keys are still withheld.

- `civex dump` and `civex restore` lost field restrictions: a restored
  reference field no longer pointed at its schema, so the record form had no
  records to search. Dumps now include each field's restrictions (including
  min/max, units, choices and file rules) and default value, each schema's
  record name template, and each collection's timezone, and restore applies
  them. Dumps made by earlier versions don't contain this information, so
  restrictions on a project restored from one must be set again by hand.

- Importing a dump through the web UI (`POST /restore`) ignored field
  restrictions, defaults, name templates and collection timezones, even from a
  dump that contained them. It had its own copy of the restore code; the
  command line and the web import now share one, so they restore the same
  things.
- A project whose database was last used by a newer civex now says so
  ("was last used by a newer version of civex ... run `civex update`") instead
  of failing with `Can't locate revision`. The database is left unchanged, and
  `civex db current` reports it rather than "Pending migrations".

### Features

- `civex doctor` now checks the installation, and works outside a project:
  - another `civex` earlier on PATH that shadows this one (it names the file
    and how to remove it),
  - required packages that are missing or at the wrong version,
  - whether `uv` is found, and whether a custom plugin's Python can start.

  Inside a project it still checks data integrity. It exits 1 only when a
  check fails outright; a shadowed copy or missing `uv` is a warning.
- `civex update` now verifies that every package civex needs is installed
  (also when already up to date) and reinstalls any that are missing, and
  warns after an upgrade if typing `civex` still runs an older copy.

## v1.1.3 — storage moves, run triage, record naming (2026-10-04)

### Breaking

- Five schema migrations run automatically on first connect, all additive:
  - `b8d2f4a61c93` adds `storage_transfers` (file moves between volumes) and
    `c5e1a8d37b42` adds its `control` column (pause/cancel).
  - `c4a9e17d5b20` adds `schemas.display_template`. Each schema's old
    `display_fields` list becomes the template joining the same fields with a
    space, so every record keeps its name.
  - `e1d5a39c7b84` adds `workflow_jobs.trigger_detail`. Runs that predate it
    simply have no recorded cause.
  - `f2a6c8d1e093` adds `audit_batches` and `audit_log.batch_id`, so a bulk
    operation is one history event. Earlier entries are unbatched.
- The `civex.load_csv` plugin is replaced by `civex.parse_table`, which reads
  any delimiter (CSV, TSV, ...) and can read several kinds in one step.
  Workflows that name `civex.load_csv` must be updated.
- Records are now named from a schema's name template instead of its starred
  `display_fields`. Old dumps still import.

### Features

- **Moving files between volumes.** Drain a volume or gather a collection's
  files onto one drive, with pause, resume, cancel and progress. Transfers
  queue and run one at a time, from the CLI (`civex store move`,
  `civex transfers ...`) or the server. Every file is verified against its
  hash before the original is removed. Settings → Storage has a Tasks tab.
- **Per-collection storage homes.** A collection can name a home volume and
  say whether to spill elsewhere or fail when it is unavailable. Content
  already stored is never duplicated.
- **Volumes are managed in Settings → Storage**: guided Add volume with a
  folder browser, a checks-before-adding step, network-drive detection, a
  page per volume, "where are my files" for every collection, and a
  per-volume clean-up. A missing drive is reported as offline with the
  reason and what to do, rather than as empty. Records show where each file
  is stored (`civex store where`).
- **Record name templates.** Name records with literal text and formatted
  values, e.g. `{site}-{taken_on:YYYY-MM}`, including one hop through a
  reference (`{ref.field}`). New schemas start with a visible template, and
  renaming or deleting a field rewrites the templates that use it.
- **Activity and retention.**
  - History is one filterable list (`/activity`, `civex history`) with
    field-level changes and where the item is now (live, deleted or gone). It
    replaces the Recently Deleted page (`civex trash list` for the CLI).
  - Bulk deletes, restores, workflow runs and browser imports each show as
    one event. A group restores only what was deleted with it, and a record
    can't be restored under a deleted collection, schema or parent.
  - Revert a record edit or create from its history entry, with a preview.
  - `[retention]` settings (Settings → Retention, `civex retention`,
    `POST /retention/run`) for deleted items, change history and runs. All
    keep forever by default, previews first, and never run by themselves.
  - Permanently deleting a record removes its audit entries and leaves one
    tombstone; `civex retention forget-purged` cleans up earlier purges.
  - Runs and reference values pointing at a deleted or purged record link to
    its history instead of a dead page.
- **Text box field type** (`longtext`): multi-line text with an optional
  `max_length`, available in the field picker, CLI and import wizard.
- **Workflow runs.**
  - An automation kill switch (stop and resume all) and per-run cancel.
  - Each run records which field change started it and the run that caused
    it.
  - Filter, sort and search runs with the records' filter; failure groups;
    re-run by filter; "completed with problems" status for runs that left
    things undone.
  - Bulk-run a workflow on selected records (`POST /workflows/{name}/run-many`).
  - A run page with Summary, Steps and Records touched tabs.
- **New menu and Add another.** Inside a record, New offers every allowed
  child schema; the new-record form gains "Add and add another".
- **Desktop shortcut.** `civex shortcut` (also in Settings → Advanced)
  creates a launcher that runs `civex serve --open`; works from WSL.
  `serve --open` opens the browser once the server answers.
- **UI.** A bottom status bar shows file moves and workflow runs; shift-click
  selects a range in every checkbox list; browser tabs are titled by
  context; explanations moved into tooltips and big pages into tabs held in
  the address; filter, sort and search for runs and history.

### Fixes

- Failure groups and bulk re-runs on a record's Runs tab are scoped to that
  record; they used to show, and could re-run, the whole project's failures.
- A workflow watching a file field no longer re-triggers itself on every save
  (derived `resolved_filename` was counted as a change).
- `civex.upsert_records`, `save_field` and `save_fields` no longer erase a
  record's other fields; they merge only what they were given.
- `civex.match_files_to_records` skips and reports files whose keys clash
  rather than silently overwriting records.
- A dead network mount no longer freezes requests; its volume shows as
  offline. `config.toml` is written atomically.
- The page-size menu now changes the size and returns to page one.
- Windows: `civex view export` leaves no open temp file, moving a SQLite
  database keeps `C:` paths intact, timed-out plugins are killed, and the
  folder browser's Up from a drive root is correct.

### Internal

- The OS-sensitive tests (storage, paths, processes, mounts, config) now run
  on Windows and macOS in a cross-platform workflow; LF line-ending rules
  added. Fixed type errors only `tsc -b` sees, and several flaky tests.

## v1.1.2 - startup and scaling reliability, geographical data types (2026-10-02)

### Features

- Web server when started would send a number of HTTP requests to the API,
  each of which would attempt to apply migrations to the datbaase schema.
  This fix does two things:
  - Run database migrations when the server is first started, not just
    when the HTTP endpoints are hit.
  - Put a lock on database migrations preventing a race condition.
- Add quick access and recent collections in the nav bar in order to facilitate
  quick access for users. Data for recent and favourits are stored in browser
  memory, not in a database.
- Add a database wide search for a Ctrl+K quick access bar. This was inspired
  by Ctrl+Shift+P functionality in VSCode.
- Add the following data types:
  - geo (for geographic types)
  - partial dates
  - float units


## v1.1.1 — collection timezones, scalable file store & queries (2026-09-30)

### Breaking
- Two schema migrations run automatically on first connect; both are
  additive, but the first backfills from existing data, so expect a pause on
  large installs:
  - `e5b81c3d7a04` adds `stored_objects` (file inventory),
    `file_references` (record/job → blob links, kept in sync by ORM events),
    `job_affected_schemas`, and indexes for the job queue, audit log, step
    analytics and record trees. Existing records and jobs are backfilled.
  - `7c2e9d4a1b58` adds a nullable `datasets.timezone`. No backfill: `NULL`
    means "unset", which is how every existing collection already behaves.
- Datetime values written through the API are now normalised to UTC. Before,
  only the CLI did this and the API stored the raw string. Offset-less values
  are read in field zone > collection zone > UTC; malformed values and times
  that a DST change skips or repeats are rejected with an error.
  `extract_from_filename` now returns offset-less datetimes (a filename
  timestamp is local wall time, not UTC), so they are localised by that same
  rule.

### Features
- **Collection and field timezones.** Collections take an optional IANA
  timezone (API, `--timezone` on the CLI, a picker in the UI; an empty value
  clears it). A datetime field can override it with a `timezone` restriction.
  The UI shows datetimes as wall time with a zone abbreviation (UTC on
  hover), edits them in the effective zone, sends UTC, and applies min/max
  bounds and view filters in that zone. The CSV import wizard says which zone
  offset-less times will be read in. Sync bundles carry the zone, and an older
  peer's bundle cannot clear a local one.
- **Editable child-record table.** The read-only child table on record pages
  is now editable in place (click, Enter or F2 to edit; Enter or blur saves,
  Esc cancels), with a draft row for creating child records. File and
  reference fields edit in a popover.
- `civex store gc --rebuild-refs` recomputes `file_references` from scratch
  if it is ever in doubt (raw SQL edits, an import that bypassed the ORM).
- Jobs can be filtered by `affected_schema`.

### Performance
- **File store.** Usage is read from the `stored_objects` inventory instead of
  walking the store on every request, and GC reconciles the inventory against
  disk so drift self-heals. Uploads (multipart is now chunked) and downloads
  (with Range support) stream instead of buffering whole files. GC checks
  bounded batches against `file_references` rather than loading every record
  and job. Dedupe hits now refresh an object's mtime, so the GC grace period
  applies to them.
- **Queries and exports.** View preview/export, collection CSV, dump and zip
  exports now sort, filter and page in SQL and write to temp files. Trash and
  job lists are paginated, and the AI count tool uses a SQL count.
- **Web UI.** Routes are lazy-loaded and heavy vendors split out (entry
  bundle 1.85 MB → 290 kB; CodeMirror, xterm and recharts load on demand).
  Idle job-count polling backs off, and stale record-picker responses are
  dropped.

### Fixes
- Purging a job that had step executions no longer fails (the bulk delete
  skipped the `step_executions` cascade).
- Accessibility: `aria-sort` now sits on column headers, and clickable table
  rows are keyboard-activatable.

### Security
- Bumped the transitive dependencies `urllib3` 2.7.0 → 2.8.0
  (CVE-2026-97687/97688/97689) and `virtualenv` 21.6.1 → 21.14.1
  (PYSEC-2026-4011..4014), plus `python-discovery`. Only `uv.lock` changes.

### Internal
- Route error boundary; colour-token migration finished with a wider
  hardcoded-colour lint; React Testing Library component tests for
  `DynamicField`, `RecordForm` and `MapStep`; `SchemaFieldsSection`
  extracted from `SchemaDetailPage`; `jsdom` pinned to `^27` so frontend tests
  run on Node 20; `tzdata` added for platforms without a system tz database.

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
