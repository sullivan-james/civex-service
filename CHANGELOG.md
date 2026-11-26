# Changelog

One section per tagged release: `## vX.Y.Z — <label> (YYYY-MM-DD)`. Every
`v*` tag must have a matching entry here *before* the tag is pushed —
`.github/workflows/release.yml` fails the release job if it's missing (see
PRODUCTION_READINESS.md §4a). A pre-release tag (`v1.3.0rc1`) may use the
final version's entry or `## Unreleased` instead of one of its own. The version itself has one source of truth,

- **Sync: a change already true is dropped, not written again.** A pushed delete
  of a record already deleted on the authority, a restore of one already live,
  or an edit or move that leaves a live record as it is, is acknowledged and
  writes nothing (no second history entry, no settling entry), and a run of
  deletes or restores that overlaps what is already done stays one bulk write of
  the rest.
- **Sync: a record that breaks a data rule is taken in and flagged.** A required
  field left empty, or a value outside its field's restrictions (min/max,
  choices, length, date range or precision), no longer refuses a pushed record:
  it goes in as sent and the answer carries an `unfit` item per field (a new
  conflict kind, code `data`). The authority's rules decide, so data saved
  under older rules can arrive flagged. Still refused: a value of the wrong kind
  (a list in a text field, a malformed date), a taken unique key, a missing
  reference, and, for now, file (`accept`, `max_size`) and geo restrictions. The
  pusher's item clears when the copy is level with the authority and the record
  no longer breaks the rule (fixed, deleted or the rule relaxed elsewhere).
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

## Unreleased

### Changed

- **Files on a host have no drives.** Where a host offers accounts and no drives
  (a hub), the Files tab, a record's files and exports show no drive, volume or
  storage location, and no way to change a drive, free up space or manage
  folders. A file that isn't there says "Not on the hub yet. It will appear
  when the device that added it next syncs." (naming the device when known); one
  that can't be reached right now says "Temporarily unavailable. Try again
  shortly." Moving files between drives (`/file-access/gather`, a release's
  `files/gather`) answers 501 where there are no drives. Desktop and self-hosted
  projects are unchanged.

### Fixed

- **Sync: deleting several records that have children in one call no longer
  half-applies.** A delete (or exact restore) of two or more trees logged its
  entries level by level, so the authority settled each parent alone, refused
  it for the child sent with it (`conflict`: something added beneath it), and
  left the parents live. Each tree's entries are now logged together, and a
  device sending a log made level by level (its own, from before) keeps every
  tree whole within one request, and the authority gathers a push's entries
  of one action that arrive apart. A 2.3.x device that already splits a tree
  across separate requests is not fixed on the server: update it.

- **Sync: a pushed bulk delete or restore of records is written in bulk.** A run
  of single-record deletes (or restores), as a bulk action on a device sends
  them (each with its `op` and `batch`), is checked together (what is held,
  children, hidden referrers, data rules and keys on a restore, permissions) and
  written with one UPDATE per stamp, one numbering, and one insert each for
  history (with its batch) and answers. Anything not certain (not here, already
  deleted, edited on the server, a record beneath it, a clash) is settled one at
  a time as before, with the same answers and rows. Settling a record's delete
  or restore no longer discards everything the push holds. Measured on
  PostgreSQL, authority only, about 0.3-0.4 ms per record instead of 17-19 ms.
- **Sync: a device applies a bulk delete, restore or edit from the feed as a set.**
  A pulled page's runs of like record changes (deletes, restores, makes, edits)
  are written in a few statements for the run (one history insert, one
  `UPDATE ... IN` per stamp for deletes, one read of the records) instead of
  six to eight per change; a change that is not plain (held, ours, repeated,
  moving a record, arriving) goes one at a time in its place. Results, holds
  and conflicts are unchanged. `benchmarks/bench_bulk_pull.py` measures it.
- **Sync: a refused schema or field change is kept and marked, not put back.**
  When the authority's data or structure refuses a schema or field change (code
  `data`), it answers `rejected`, writes nothing to the feed, and refuses the
  whole action it was part of. The device keeps its version until the person
  sends it again or discards it (which takes the server's version). No protocol
  bump: an older device given `rejected` for a structure change keeps its
  version but does not hold the server's later changes to it, by design.
- **Store-to-store file copy for hosts.** `civex.context.copy_objects(source,
  destination, shas, on_progress=, commit=)` copies content-addressed files
  between two stores from `make_store` and returns a `CopyResult` (`copied`,
  `skipped`, `absent`, `bytes_copied`, `methods`). Drive to drive hard-links
  on one filesystem, else copies; bucket to bucket on the same endpoint,
  profile and region is a server-side `copy_object` (`upload_part_copy` past
  5 GiB); anything else streams with no temp file (multipart from the ranged
  reader into a bucket). Shas are validated, files the destination holds are
  skipped, a source whose bytes don't match its name is refused, and the
  destination's inventory is written as a put writes it.
  `ReleaseService.write_copy` takes an optional `on_progress(done, total)` in
  bytes.

- **Structure changes need unrestricted read; collection delete checks hidden
  referrers.** `Permissions` now drops `change_structure` whenever read is
  limited to some collections (kind create/rename/templates, field add/update/
  restore/delete, collection create/rename/restore), so the services, the data
  API and a sync push (`refuses`) all meet one rule. Deleting a field also needs
  `delete` (`action_for`, the service and a push). Deleting a global collection
  (or making it local) is refused while records the caller cannot see point
  into it. A push follows the same rules: a record delete or purge with hidden referrers, and a collection delete or global-to-local change with any live referrers (one shared rule, `RecordService.collection_referrer_block`), is refused. An explicit `release` grant is withheld from restricted readers too. Documented that revoking a
  device or narrowing access never wipes what it already synced.

- **Files still being uploaded show as "Uploading", not "missing".** On an
  authority, a file not here is `arriving` (record location state, `arriving`
  in the Files tab's places, and not a `missing_file` in the data check) for
  `[sync] arriving_hours` (default 24, 0 = no allowance) after a device sent a
  change that was taken (applied or merged, never refused) and that added or
  changed that very file on that record. An unrelated edit, or a refused
  change, does not start the wait; after it, or once the file is uploaded, it
  is as before. One batched lookup per page of records, only when one cites a
  file not here. The push path does no extra work beyond one more index on
  `sync_ops` (migration `a4e9c2b7d6f1`). Building it blocks writes to
  `sync_ops` while it runs, which on an authority with a very large change
  history can take a while: run the upgrade when pushes are quiet.
- **Records created and then deleted before their first upload no longer slow a
  push 15-fold.** The authority took a record that arrives already deleted one
  at a time (about 9 ms each); it now writes it in bulk with the rest of its
  run, as it does a live one, to the same rows (a deleted record holds no
  unique key and its references are not asked about, as before). The client
  still sends such records as they are: they are in the trash, and the server's
  copy is what lets another device restore them and see their history.
- **Checking that records still differ on a uniqueness key is a query that
  stops at the first duplicate, and runs only when it can have changed.** It no
  longer reads every record of the schema into memory under the push lock, and
  a schema change that does not touch its keys (a label, a description) skips
  it. The answers are the same.

## v2.3.1 — release screens left to the host (2026-11-24)

- **civex no longer has a release wizard.** The "New release" page and button
  are gone from the app (they appeared only on a host, where the host's gate
  refused the final request). The read-only views (list, a release, compare,
  downloads) and the whole engine and API stay.
- **`onRelease` embed option.** In the records list, "Release these…" now hands
  the selection to the host: `mount(el, { onRelease(scope) {...} })`, where
  `scope` is the JSON of `ReleaseScopeRequest` (`{ records: [...] }` or
  `{ query: {...} }`). Without a handler the item is not shown.
- **A scope on the allowed surface.** `ReleaseScope` now lives in
  `civex.domain.release` (still importable from `civex.services.release_service`),
  and `ReleaseScopeRequest` in `civex.server.models`, so a host can build a scope
  and call `release_svc.create` / `plan` without importing `civex.services`.
- **Records by when they were added.** Every record query (listing, counts,
  exports, release scopes and plans) takes `created_after` / `created_before`
  (ISO 8601, naive means UTC; after is inclusive, before exclusive). A stored
  release scope keeps them as ISO strings. Selecting by kind already worked
  (`schema` / `schema_name`).

## v2.3.0 — upload speed, hub-only releases, embeddable data views, sync fixes (2026-11-24)

#### Breaking

- **Releases are hub-only and never synced. Sync protocol 6.** A release is
  published on a host (a civex hub), not made on a personal device, so it no
  longer travels. A host that wants releases turns on the new `RELEASES`
  feature (off by default; not in `LOCAL_FEATURES`). Every `/releases` route
  (making, correcting, withdrawing, yanking, listing, reading, comparing, the
  files, the bundle) and the app's Releases pages are gated by it: with it off
  they answer **404** (a project on a host that mounts the router without the
  feature answers 501), and the app hides them.
  - **Sync:** the authority never feeds or snapshots a release, hello counts
    leave them out, and a push of one is refused (`rejected`, code
    `not_synced`, "Releases are published on a civex hub"); a protocol 3-5 peer
    that sends one is refused the same way and one that asks for
    `/snapshot/release` gets an empty page. A device no longer sends releases or
    counts them as unsent, and release-owned `file_references` are not files it
    sends or fetches (they stay on the host that made them, so clean-up still
    keeps them). Update the authority first. Releases already held by an
    authority keep working there (REST); they are just not fed.
  - **Desktop:** the whole `civex release` command group is gone (it only
    says "Releases are published on a civex hub"), as are the app's release pages
    and the explorer's "Release these...". **Releases an older civex made on a
    computer are no longer listed, verified, cited, compared or exported there**
    (their rows and bundles are left in the project, untouched; nothing converts
    them). Take a hub's release with `civex clone <repo-url> --release NAME`.
  - **A new `RELEASE` permission** replaces `change_structure` for making,
    correcting, withdrawing and yanking. A host that says nothing about it gets
    it wherever `change_structure` goes (roles behave as before); granting it
    alone allows releasing without editing the structure, and `lacking` it
    takes it away alone. `GET /releases/{name}/bundle` now answers 200 with one
    bundle that includes the release's files (it was a redirect to a bundle of
    records only).
- **No migration.** Nothing is converted: existing release rows, their
  bundles and file ownership are untouched.

#### Added

- **`civex clone <repo-url> --release NAME`** downloads a hub's release bundle
  (records and files, streamed to disk in chunks) and reads it into a **new**
  project that follows nothing. It starts read-only (`[project] read_only` in
  config.toml; `--writable` to allow changes); `--token` (or `CIVEX_TOKEN`)
  authorises a private repository. Workflows and plugins in the bundle are not
  installed. Over plain HTTPS it is the same as downloading the bundle and
  running `civex bundle import`.

#### Added (bulk file upload)

- **Small files go many to a request.** Files under 8 MiB are sent in packs of
  about 32 MiB or 100 files (`PACK_BYTES`, `PACK_FILES`), four packs at a time,
  to `POST /sync/v1/files/pack` (capability `file_packs`, no protocol bump). The
  authority reads the body as it arrives (never whole in memory), hashes and
  stores each file, and answers per file, so one that fails (hash mismatch, a
  full drive) keeps the rest: the sender confirms exactly what was answered
  stored. A pack is one HTTP request. An authority without the capability is
  sent one file per request as before. Over SQLite the authority commits before
  each wait for bytes (one writer); elsewhere every 25 files; a pack records its
  files in the inventory in one statement.
- **Big files go in parallel parts.** A file over two parts (32 MiB) is read once
  and sent in 16 MiB parts, four at a time, at most four parts in memory. In a
  bucket (`direct_files`) those are S3 multipart parts (files over 32 MiB now go
  multipart instead of one PUT; before, up to 5 GiB went as one stream). On an
  authority with files on drives the same shape is `POST /files/{sha}/parts`,
  `PUT /files/{sha}/parts/{n}`, `POST /files/{sha}/parts/complete` (capability
  `file_parts`): parts are written in place, an interrupted upload is picked up
  by asking which parts are held and sending only the rest, and the whole is
  hashed once at the end. A big file is never packed or mixed with others.
  A 429 or 402 on any of these still stops the pass and backs off.
- `benchmarks/bench_bulk_files.py` times a many-small or few-huge upload to an
  authority in its own process, files on a drive or in a bucket.

#### Changed (bulk file upload)

- Where `direct_files` is on, small files are not packed: a pack streams bytes
  through the authority, and direct is what keeps them off it. They go one
  presigned upload each, four at a time, as before; only big files change
  (multipart, in parallel).
- The authority commits a streamed file (`PUT /files/{sha}`) before answering,
  so a write lock is not held while the next upload is read (on SQLite parallel
  uploads could stall until their timeout).

#### Changed (one client transport)

- **Every call to an authority goes through one HTTP client**
  (`services/http_wire.py`): connect/join, device sign-in, sync, files, packs,
  parts, storage URLs, the library and `clone --release`. It keeps one
  keep-alive connection per thread and host (a pass no longer pays TCP and TLS
  for every request), sends `Accept-Encoding: gzip` on JSON calls, and never
  takes the session to another host on a redirect or gzips file bytes.
  A push body is gzipped only when the server's `hello` lists the new
  capability `gzip_requests`; older servers get plain JSON as before.
- **One status table.** 429 and 503 wait what `Retry-After` says (seconds or a
  date, capped at 120 s, +-25% jitter) and send the same request again inside
  the pass, a bounded number of times; network errors, timeouts and other 5xx
  back off exponentially with jitter. 402 and 413 are refused at once with a
  message ("this change is too big to send in one go"). A call that still
  fails carries `SyncError.retry_after`, which the background worker waits on.
- **Timeouts by call type:** pushes 120 s (`CLIENT_PUSH_TIMEOUT_SECONDS`),
  other JSON calls 60 s, uploads 120 s, finishing a big file 600 s.
- The background worker jitters the poll interval, the sync interval and its
  failure back-off, so devices that failed together do not retry together.
- **Pushes are batched by bytes as well as entries** (about 2 MiB serialized,
  never splitting an action; an oversized action goes alone), and a push that
  the server answered short now carries on with the rest in the same pass
  (stopping when an answer settles nothing).

- Review fixes: the client honours the system and environment proxies
  (`HTTPS_PROXY`, `NO_PROXY`, ...; a CONNECT tunnel for https) including for
  `clone --release`; a call that is not safe to repeat (join, device sign-in
  start, finishing a big file, publishing) is resent only on 429/503 or when
  it never went out, and says so when its answer was lost; connections are
  pooled across threads (at most 8 idle per host), released when a download is
  closed and closed when a sync pass ends, so big uploads leave no sockets.
- **Clone/connect without an invite signs in in the browser even when this
  computer joined that server for another project.** Each project is its own
  device, so the client now asks the server whether it knows this device
  instead of guessing from a per-machine record. Device refusals carry a
  machine-readable code (`not_a_device`, `clock_skew`, `bad_signature`) in an
  `X-Civex-Code` header; the message text is unchanged for older clients. A
  revoked device signs in again the same way; other refusals keep their messages.

#### Changes

- **A first upload that was interrupted always resumes.** A project whose
  history was all settled with another server set no changes aside for the
  upload, so nothing marked it unfinished: after the connect failed (or either
  side restarted) the next sync sent nothing and the new server kept only the
  part that had gone. `sync_meta.seed_open` (automatic migration) now records
  that an upload began and is cleared when it finishes; the next sync or
  connect finishes it, using the seed acks to skip what was answered. A sync
  also says so (`notice`) when the server is behind where this copy had followed
  it, instead of quietly sending nothing.
- **A first upload to a hub is much faster.**
  - A first upload (seed) that is interrupted or reconnects **resumes after what
    the authority already answered** instead of sending the whole project from
    the start: each answered batch is remembered (new table `seed_acks`, added
    by an automatic migration; cleared when the seed finishes) and left out
    next time.
  - Records go in batches of 250 (was 100); the authority takes at most 500.
  - Files: the slice's locations and sizes are looked up in one query; files up
    to 8 MiB (`sync_service.LARGE_FILE_BYTES`) go four at a time over HTTP and
    are confirmed and committed in groups (50 files or 2 s); a larger file is
    always sent alone, one at a time, and confirmed and committed as soon as it
    arrives. A failed upload still keeps the files of its group that arrived.
  - The Files page's list (`POST /api/file-access/files`) keeps an answer that
    took 0.3 s or more for 3 s, so the screen's refreshes while sync runs don't
    each recompute every file; any other `/file-access` call drops it.
  - `benchmarks/bench_first_upload.py` measures it on PostgreSQL.
- **An authority writes a pushed batch of new records in bulk.** A run of
  records made new (no parent, no uniqueness key, no references to other records)
  is validated against schemas and collections read once per run, then written
  with one statement each for the records (and their file and record
  references), the history rows, the answers kept and the feed numbers (one
  `head_seq` update), instead of about 11 statements per record. On PostgreSQL
  with 200k records already held, a seed batch of 250 went from about 7.0 ms to
  0.4 ms per record on the authority. The answers, the rows and the numbers are
  those of settling each change alone (tests compare the two); anything else (a
  refused or invalid change, a clash, an edit, a delete, a child record, one
  whose id or entry appears twice in the push) is settled one at a time as
  before, in the order sent. The first upload's client does one lookup of open
  refusals per batch rather than one per change (0.65 to 0.14 ms per record on
  PostgreSQL). `benchmarks/bench_bulk_push.py` measures both.
- **The bulk write takes records with a parent, references and uniqueness
  keys.** A record under a parent (stored, or made earlier in the same push), one
  citing other records, or one in a schema with a uniqueness key is written in
  bulk too. A push reads once, with one query, where every record it sits under
  or points at is, and, per collection and schema, which uniqueness keys nothing
  stored holds; records the push makes are added as it goes, so a child is judged
  with its parent there and two records sharing a key in one push are settled
  one at a time (the second is refused as before). Records the batch refuses, a
  parent that comes after its child, a parent in another collection and callers
  limited to some collections take the one-at-a-time path as before. Changes
  settled one at a time also use the schemas, collections and records read for
  the push instead of reading them again. Answers and rows are identical
  (`tests/sync/test_bulk_push.py`). `bench_bulk_push.py --shape parented` times
  the parent/child shape.

### Workflow steps (breaking)

#### Breaking

- **The built-in workflow steps are redesigned for people who don't program, and
  every step now has a version.** Eleven steps became five, in three groups
  ("Bring in", "Work out", "Save"), named in a workflow with their version:

  | New step | Replaces |
  |---|---|
  | `civex.files@1` (Files: chosen when run, a folder on this computer, or a field of the record) | `civex.load_file_list`; workflow `inputs: {x: {type: files}}` |
  | `civex.table@1` (Table: CSV, TSV or Excel from a Files step or a file field) | `civex.load_file` + `civex.parse_table` |
  | `civex.value_from_filename@1` | `civex.extract_from_filename` |
  | `civex.save_records@1` (Save as records: rows or files; `if_exists` update, skip or add_new) | `civex.rows_to_records`, `civex.upsert_records`, `civex.create_records_from_files`, `civex.match_files_to_records` |
  | `civex.set_fields@1` (Set fields on this record) | `civex.save_field`, `civex.save_fields` |

  `civex.get_field` is gone as a step: any setting of any step may be written
  `{from_field: name}` to take its value from a field of the record the workflow
  runs on. The old ids no longer run; an id without a version means version 0.
- **Workflow files are upgraded automatically.** When civex loads a workflow
  file written for the old steps (or a workflow is pasted, shared or saved), it
  rewrites it for the new ones: old steps are mapped one to one, `load_file` +
  `parse_table` merge into one Table step, and `inputs: {x: {type: files}}`
  becomes a Files step named `x` with the later steps rewired. The old file is
  kept beside it as `<name>.yaml.bak` (not a workflow, not synced) and the change
  is logged. Comments in the file are not kept in the rewrite (the backup has
  them). A workflow that can't be mapped by itself (a step of your own reading
  `load_file`'s file name, say) is left untouched and the error says which step
  to edit. A workflow naming a step version this civex doesn't know is refused
  ("needs a newer civex") rather than guessed at, since workflow files sync
  between computers. Future contract changes follow the same path: a new step
  version plus an upgrade function (`workflows/upgrades.py`), with golden tests
  per version (`tests/workflows/test_step_upgrades.py`).
- **Run-time files are asked for by a Files step.** A run's files are given under
  the step's id (`civex workflow run x --input <step id>=*.wav`; the run dialog
  and the API use the same name). The old workflow-level `inputs` of type `files`
  are upgraded into such a step; plain `value` inputs are unchanged.
- **Table reads commas, tabs or semicolons by itself** when no separator is
  given (the old Read a table step assumed commas).

#### Added

- **Read a folder on this computer.** A Files step set to a folder (or the run
  dialog's "choose a folder on this computer") reads the files from disk itself:
  nothing is uploaded, files whose content is already stored are skipped (by
  content hash) and the run shows its progress. It needs the new
  `server_path_import` feature, on for a computer's own civex and off on a host
  (a hub never reads host paths), and a built-in-only host function
  (`store_folder`) that no plugin gets from a permission action.
- **Table reads Excel (`.xlsx`) files**, and several files at once.
- The workflow builder offers the steps in their three groups, shows a step's
  settings only when they apply (the folder, once "A folder" is chosen) and lets
  a setting take its value from a field of the record.

### Sync server policies and fixes

#### Sync server policies (no protocol change)

Server-side only, or advertised in `hello`; older devices keep working.

- **One page budget for every paged read.** Feed, snapshot and history pages
  stop at 2 MiB of entry payload as well as at `limit` (now an "at most"), and
  `more`/`next` is decided in one place (`domain/sync_page.py`) as "the page
  stopped before the end". Only the rows of a page are loaded. An action is
  kept whole while it fits a page (up to 5,000 entries); one over the budget
  alone is cut and says `more: true`. Fixes the feed cutting an action of
  over ~400 entries and answering `more: false`.
- **One request-deadline policy on `/sync/v1`**, at router level so a host that
  mounts `api_routers` gets it: on PostgreSQL `SET LOCAL lock_timeout` (30 s)
  for the feed lock and numbering, and `statement_timeout` (15 s) for
  hello/feed/snapshot reads (never session-level; numbering a backlog is exempt
  from the statement timeout). A wait that runs out is `503` with
  `Retry-After` (`BusyError`), also on a docker-managed project. A push that
  has run for 10 s (`PUSH_BUDGET_SECONDS`) finishes its current action and
  answers for what it settled; the device sends the rest next.
- **One wire-encoding policy for JSON routes.** `push` accepts a
  `Content-Encoding: gzip` body, read after the caller is authenticated and
  inflated off the event loop up to 64 MiB (`CIVEX_SYNC_MAX_REQUEST_BYTES`;
  over it: `413` `{"code": "too_large"}`); every other route answers `415` to a
  compressed body. `hello` advertises `gzip_requests`. JSON answers over 1 KiB
  are gzipped for a caller that sends `Accept-Encoding: gzip`, except those of
  `push`, `join` and `device-login` (a host in front reads them). Files, packs,
  parts and downloads are never compressed.
- **File parts no longer race.** Beginning or finishing the parts of one file
  takes a per-file lock (a lock file on the volume naming its owner's process
  id and start time, valid across processes and on Windows; a stale one is
  taken over by one waiter at a time); two `begin`s never wipe each other's
  parts, `finish` is idempotent (the file already stored is success, not a
  507), and a part that lands after the file was stored is accepted. A part and
  a finish for the same file never overlap: whichever sees the other's marker
  backs off with a retryable 503 (`upload_busy`).

#### Other changes

- **File uploads work when civex is embedded in a host.** The browser uploads
  (a file on a record, files into a collection) are XHR so they can show
  progress, which skipped the host's sign-in and answered 401. A host now
  supplies request headers for them: `headers()` in the mount options
  (`embed.tsx`), or `window.__CIVEX_HEADERS__` on a page civex serves.

- **A file field's attachment list reads properly on a phone.** The file
  name now takes the row's width (cut with an ellipsis, full name on hover)
  and the size and remove button wrap beneath it instead of squeezing the name
  away; sizes use KB, MB or GB (55707.6 KB is now 54.4 MB); a file with no
  name shows its short hash.

- **A restore of a record the server once refused goes in as a restore.** A
  device remembered that a server had refused a record's create even after a
  later fill of a server (following another one, or filling the same one again)
  had sent the record and been taken. Every later edit or restore of it was then
  sent as a create of the record as it is: a restore made after pulling a
  delete from the server met that delete as an "edit" and was refused with the
  rest of its tree ("deleted on the server, and edited here", "part of one
  change that could not go in whole"), and the records went back to deleted.
  Filling a server now notes, on the refusals of what it took, that it was
  taken (new column `sync_conflicts.taken_at`, with an index on
  `sync_conflicts.entity_id`; how a person settled a refusal is left as it was,
  so letting one go can still be undone), and a refusal of the same thing by a
  server filled again after a reset says it is missing there again. Copies
  that already hold such stale refusals are not repaired (re-clone them).
  Also: following another server settles what was waiting for review as
  `followed` (it wrote "followed another server", longer than the
  column, so a device on PostgreSQL could not follow another server).
- **Undoing a bulk action is one step, however big, through one code path.**
  Restoring what a bulk delete took stopped at 5,000 records (and eight rounds
  of parents first): a delete of 69,574 records offered "Restore" and then
  brought back 5,000, "5,000 records in all". There is no cap now, and undo is
  no longer a path of its own: `RecordService.apply_changes` takes a set of
  record changes (delete, restore, put fields back), plans it in memory from
  the few columns it needs, writes it a chunk at a time (5,000 ids, 2,000
  history entries per statement, a fixed number of statements per chunk, never
  one per record) and records it with the new bulk history writer. Bulk
  delete, bulk edit's chunks, restore-all, a restore from Trash and the undo
  of any bulk action (`revert_batch`: now a bulk edit, a delete or a restore;
  the inverse change set is read from the batch's history) all use it, and the
  old per-kind paths (one-at-a-time reverts, the eight-pass loop, a history
  entry per `log_change`) are gone. What is left deleted is only what is
  genuinely held back (a collection, schema or record above it that is deleted
  and not coming back, or a clash of unique values) and is counted; unique
  keys are checked a chunk of records at a time instead of per record. The
  preview and the restore are the same computation, so the dialog's numbers
  are exactly what happens. An undo is one step and one batch in history; each
  tree it restores is its own action when sent, so one refused tree splits
  nothing else, and a preview runs the same checks as the undo (referrers,
  permissions, `force`). The History restore dialog shows the true
  count and a busy state. `GET /audit/restore-all` no longer has a `truncated`
  field. History entries go in with COPY on PostgreSQL (about 30k rows/s through the
  driver, against 5k/s before). Measured on PostgreSQL with 69,572 records:
  delete 10 s, undo preview 3.6 s, undo 8 s, redo 13.5 s.

- **Faster pushes to an authority.** A push of 100 changes ran about 17
  statements per change (20 for edits), all under the feed's lock; it now runs
  about 10 (13 for edits): what the push asks one change at a time (was it sent
  before, the record it names, the feed's row) is read once for the whole push,
  and the feed's counter comes back from the statement that raises it. Asking
  which of 1000 files the authority lacks (`missing_files`) was 1000 statements
  and is now 4. Same answers, order and audit; no change to the wire. Measured
  by `benchmarks/bench_push.py` (PostgreSQL: 1.37 s to 0.85 s for 100 new
  records, 535 ms to 37 ms for 1000 hashes).
- **Sending a large project's files shows one total from the start.** The
  total of the "files sent" bar used to grow, because each background pass
  only counted the files it had already asked the server about, and the
  server was asked about every file still owed, again, on every 20 s pass
  (tens of thousands of `files/missing` calls on a big first upload, all
  charged against the upload time). The total (files, and their bytes) is now
  one aggregate query over the references and the file inventory, so the bar
  reads "x of N files · a of b GB" from the first moment and holds steady.
  A pass asks only about the slice of files it is about to send, time spent
  asking no longer counts against the upload budget, and a file the server
  already holds counts as done; one that can't be read here is shown apart
  ("N not readable here"), never as sent. An `everything` pass still checks every file,
  so one the server has lost is found and sent. Resumable and idempotent as
  before.

## v2.2.0 — hidden collections and filtered sync, hosted chrome, CLI sign-in (2026-11-23)

### Breaking

- **Sync protocol 5.** A device whose person may not read every collection must
  be on protocol 5: on protocol 4 the authority answers 426 ("update civex on this
  device"). Update such devices (and the authority first). A device whose person
  reads everything still works on any supported protocol (3 to 5).
- **Migrations (applied automatically, all small and additive):** `a3c7e1d9f5b4`
  adds `code`, `retries` and `retried_at` to `sync_conflicts`; `c8d2f4a6b1e7`
  adds `ignored_missing_files`; `e7a1c5d9b3f2` adds `misses` and `retry_at` to
  `server_lacks`; `d9e3a5c7f1b4` adds `sync_meta.readable` (what a device was
  told it may read); `f3b8d6a2c9e1` adds a partial index on the changes a first
  upload has set aside (empty in practice), so asking whether one is unfinished is a
  lookup, not a scan of the audit log. On a large PostgreSQL project it
  briefly blocks history writes while it is built, during the upgrade.
- **New feature flags hosts must know about:** `settings`, `settings_appearance`,
  `settings_retention`, `settings_map`, `settings_advanced`, `settings_devices`
  and `settings_members` (all on locally; a host that lists its features must
  add the ones it wants). `/remote`, `/remote/files*` and `/remote/conflicts*`
  are now gated on `remote_dial` and answer 501 on a host without it. New
  permission actions: `add_files`, `delete_files`, `notes`, `views`,
  `manage_devices`.
- **Documented limits.** Taking access away cannot claw back what a device
  already copied: it stays on that computer. A grant made after a device finished
  downloading history does not backfill earlier Activity history for that
  collection: the device gets the records, but Activity shows only later changes.


### Added

- **A record shows where it stands with the authority.** `GET /api/records/{id}/sync`
  answers `synced` (authority number and when), `pending` (changes not yet sent),
  `first_upload`, `refused` (with the authority's reason), `conflict`, `not_connected` or
  `held_here`, plus how many of its files are not sent: one grouped read of the record's
  own audit entries. The record page shows it (with a link to review a refusal or
  conflict) and `civex record show` prints the same line.
- **An unfinished first upload shows.** `/api/remote` and `civex sync status` report
  `seeding` (changes still to go), the app's sync button says "finishing first
  upload", and its progress appears in `progress`.
- **Finer permissions for hosts (C3a).** `civex.domain.permissions` gains
  `ADD_FILES`/`DELETE_FILES` (`MANAGE_FILES` stays as an alias for both), `NOTES`,
  `VIEWS` and `MANAGE_DEVICES`; every action, `READ` included, can be limited to
  collections (`Permissions.of(..., read_collections=...)`, `read_scope()`). A
  collection the caller cannot read is absent everywhere (lists, counts, search,
  summaries, dashboards, exports, history, notes, files) and a direct request for
  it is a 404, enforced once at the session (`civex.db.read_scope`). Saving a
  record that cites or lets go of a file takes `add_files`/`delete_files`;
  `/remote/authority*` takes `manage_devices`. Hosts that say nothing about
  `notes`/`views` keep them following `write_records`. New
  `Project.push_accepted` host callback, called once after a device's push is
  committed. See `docs/guides/hosting.md`.

- **Sync respects what a device's person may read (C3b, sync protocol 5).** The
  authority sends a device only the collections its person may read: the feed, the
  copy a joining device reads, the counts and the files. A record moved out of
  sight reaches the device as its removal, one moved into sight as its creation, in
  full. Pushes into, or pointing at, a collection the device may not read are
  refused (not taken). When access is widened the device catches up by itself
  (`hello.readable`, `snapshot?dataset=`, `sync_meta.readable`, a migration);
  when it is narrowed the authority stops sending, and what the device already
  holds cannot be taken back. The feed reports `through`, so an unseen run of
  changes does not hold a device in place, and one request looks at no more than a
  bounded number of entries. A device whose person may not read everything must be on
  protocol 5 (older ones are told to update); a record moved while its collection was
  out of sight is read when the collection is given. See `docs/guides/sync.md` and
  `docs/guides/hosting.md`.
- **`civex files missing`** lists files records cite that this project never
  stored and nothing can supply (no copy here, none on the server), by
  collection and field. `--ignore <hash|all>` stops the warnings (the records keep
  citing them; reversible with `--unignore`, and forgotten by itself when the file
  turns up). `--remove <hash|all> [--dry-run]` clears them from the records as
  ordinary edits (history, sync), one event in Activity; a record whose required
  field would be left empty is left as it is and named. Never touches a file that
  exists here or that the server holds. Also `GET/POST /api/remote/files/missing`
  (`/ignore`, `/unignore`, `/remove`), an Ignore action on the app's missing-files
  notice, and an "Ignored" line in `civex sync status`.
- Settings features a host can switch off, because a host owns all settings:
  `settings` (the whole Settings area), `settings_appearance`,
  `settings_retention`, `settings_map`, `settings_advanced`, `settings_devices`
  and `settings_members`. A local project keeps all of them. A section feature refuses
  only the routes that edit that section's stored settings (never the operational
  `/remote/authority*` or `/retention/*` routes a host drives); `settings` off
  turns every section off and refuses editing the identity; `GET /api/status/features`
  lists them all.
- A page whose feature is off is blocked, not just hidden from the navigation:
  the terminal, plugins, workflows, runs, AI, database, storage, updates, logs
  and each settings section show "Not available here". The top-bar sync button
  and `/sync/review` appear only for a project that follows a remote, which a
  hosted authority does not.
- **Device sign-in from the CLI.** When the authority sends a `verify_url`, `civex
  sync connect` shows "Open <url> and enter the code XXXX-XXXX" instead of only
  `civex sync device approve`; authorities without a page keep the old hint.
- **`civex clone <url>` needs no `--invite`.** Without one it signs in as a
  device (shows the code, waits for approval, then copies).
- **`civex auth status`** shows the authority, this device's name and id, whether
  it has joined, and the last sync error.
- **Upgrades say so.** Upgrading a project's database can take minutes on a
  large one. The desktop app now shows a page ("step X of Y", what each step
  does, elapsed time) before opening the project, instead of timing out after
  30 s; `civex serve` migrates before it starts listening and prints each step;
  the CLI prints "Upgrading this project's database (step X of Y)" to stderr
  when there is something to do (and stays quiet otherwise). SQLite projects
  take a file lock (`<database>.migrate-lock`), so a second civex process waits
  instead of migrating the same file at once. For hosts, `civex.db.migrate`
  gains `ensure_schema_current(..., progress=)`, `pending_migrations(engine)`
  and `reporting_progress`.

### Changes

- A host can draw civex's chrome itself. The boot object (`window.__CIVEX__`,
  `render_app_page(boot=...)`) accepts `chrome: "embedded"` (no top bar, footer,
  left rail or Settings item), `theme` (CSS custom properties set on `:root`)
  and `brand` (`name`, `logo_url`). A new `app.header` extension slot draws the
  host's header and tabs at the top of every page, and each route change is
  told to the host as a `civex:navigate` event on `window` (also
  `window.__CIVEX__.navigate.on(fn)` for extensions). Without these the app
  looks as before. See `docs/guides/hosting.md`.

### For hosts

- **Converting `records` to hash partitions is public.**
  `civex.db.migrate.convert_records_partitions(engine, partitions=8)` lays an
  existing PostgreSQL `records` table out as hash partitions, and
  `records_partitioning(engine)` reports the layout (`RecordsPartitioning`), so
  a host no longer imports `civex.db.partitioning`.
- **The dial-out routes are all gated on `remote_dial`.** `/remote`,
  `/remote/files*` and `/remote/conflicts*` now answer 501 on a host without it,
  like `/remote/connect` and `/remote/sync`; the app's status poll stops asking
  there.

### Fixed

- **An interrupted first upload is finished by the next sync.** A project seeding an
  empty authority that was stopped part way (restart, dropped connection) left its
  remaining changes marked `seeding`, sent by nothing, with `pending: 0` and no error.
  Any sync (background, `Sync now`, `civex sync`) now finishes it first, whatever the
  cursor, sending the whole project again except what other devices made (it resends from the start, as
  the authority answers what it already holds); projects stranded this way heal on
  upgrade. A failure while connecting is now recorded in `last_error`.
- **Sending files could never start on a large project.** The pass's time budget
  included asking the authority which of tens of thousands of files it lacked, so it was
  gone before the first upload, every pass. Files are now asked about and uploaded page
  by page, and a pass always sends at least one.
- **Asking which files a project cites no longer scans them all per page.** On
  PostgreSQL the page query ran a `DISTINCT` over every file reference joined to records
  for each 1,000 files, slow (about 70 s for 77,000 files) and enough to exhaust the
  database container's shared memory ("could not resize shared memory segment"). A page
  now reads only its own stretch of the `sha256` index and stops at the limit.
- **Settings → History storage tells the truth on PostgreSQL.** It said "stored
  compactly" and showed no size, though tables never shrink there on their own.
  It now shows the project's size and an estimated unused part, and Reclaim
  space runs VACUUM FULL on the mostly-empty tables (off for hosts without
  `db_admin`).
- **Sync's file download works on PostgreSQL.** The step that picks a collection
  for each missing file failed with `function min(uuid) does not exist`; it now
  works on both databases.
- **Undoing a bulk edit is more exact.** Records dropped between plan and save
  are reported as left, not counted as undone; the entries of a batch are undone
  in write order; a record changed by an earlier restore or delete in the same
  undo is read again before a later entry for it is judged.
- **A busy database is no longer reported as a broken one.** A SQLite
  "database is locked" during sync was shown as "this computer's database isn't
  in the shape civex expects ... failed (will not retry until fixed)". It is now
  a transient "another civex process is using this project" failure: the sync
  waits up to 10 s for another sync on the project (`civex sync` says so and
  skips when it is still running), and retries a lock error a few times (1, 3 and
  6 s) before giving up, to be tried again by the background worker. A truly bad
  schema is reported as before.
- **Files that can't be sent no longer log one INFO line each, every sync.** One
  summary line per pass (count, a few ids); each file is at DEBUG. Files this
  project never stored (records cite them, no drive ever held them) are named in
  the summary with the collections whose records cite them, and listed in
  `civex sync status` and after `civex sync`.
- **Changes the authority refused for permission are sent again by themselves.**
  The refusal now carries `code: "permission"` (in the `conflicts` item of the
  push result; older devices ignore it, and an older authority sends none, so
  nothing is sent again by itself from it). A permission refusal is sent again 15
  minutes after it, then after 1 h, 4 h, 16 h, then daily, so a change that is
  still forbidden is not asked every sync. Other refusals (a value that breaks a
  rule) are left for a person. The sync report and `civex sync` say how many
  refused changes wait and print `civex sync resolve --all --take retry --kind
  rejected`.
- A project holding file references nobody has the bytes of no longer shows
  "Downloading files 0 of N" forever. A file the server said it hasn't got is
  remembered in the project (not in worker memory), asked for again only after a
  wait that doubles from 10 minutes up to a day, and at once when a change to a
  record citing it arrives. It is counted as "N files are missing everywhere"
  (`files_missing` in `/api/remote`, `civex sync status`, Settings, pointing to
  `civex files missing`), not as downloading, and `--ignore` hides it from both
  counts. No wire change.

## v2.1.0 — big collections stay fast, hosting hooks, partitioned PostgreSQL (2026-11-22)

### Breaking

- **PostgreSQL: `records` and `audit_log` are partitioned** (migration
  `b5d8f1a3c6e2`). `records` becomes `PARTITION BY HASH (id)` with 8 partitions
  (all indexes and foreign keys kept) and `audit_log` becomes one partition per
  month plus a default one. A database that already has data is copied into the
  new layout inside the migration: writers wait for the copy and index build
  (about 50 seconds per million records, see
  `docs/contributing/records-partitioning.md`), readers only for the final swap.
  A new database converts in milliseconds. Opt out with
  `CIVEX_RECORDS_PARTITIONS=off` / `CIVEX_AUDIT_PARTITIONS=off` (or `[db]
  records_partitions = 1`) before the migration runs; SQLite is unchanged.
  Hosts should call `civex.db.migrate.ensure_audit_partitions(engine)` daily
  to create upcoming months (civex also does when a database is migrated).

### Upgrading

- On PostgreSQL, migration `b5d8f1a3c6e2` rewrites `records` and `audit_log` in
  one transaction. Plan for writers to wait about 50 seconds and about 2.5 GB
  of WAL per million records (and as much free disk again, until the swap);
  readers are blocked only at the swap. A new or empty database is unaffected.
  Run `civex db migrate` in a maintenance window for a large database.
- `CIVEX_RECORDS_PARTITIONS` sets the number of hash partitions of `records`
  (default 8; `off` keeps one table). `CIVEX_AUDIT_PARTITIONS=off` does the
  same for `audit_log`. Set them before the migration runs.
- A host that embeds civex should call `civex.db.migrate.ensure_audit_partitions(engine)`
  regularly (daily is enough) so the next months' `audit_log` partitions exist.
- Sorting a field in descending order now lists records that tie on that field
  newest first (it was oldest first). Ascending sorts are unchanged.

### Changes

- Lists scale to a million records. Every filter, sort and uniqueness check
  reads a field's value through one expression, so a per-field index can serve
  it. civex keeps indexes for fields in a uniqueness key, plus any listed in
  `[db] indexed_fields`, builds them in the
  background (never inside a request), refreshes planner statistics, and on
  PostgreSQL uses a GIN index for equality. `civex db indexes --reconcile`
  does it in the foreground. Part of this is the visible tie order above.
- Listing a collection's files, the export preview and plan, and bulk edits no
  longer load every record: on a 250,000-record project listing files went
  from minutes to about a second. A bulk edit is planned over the set and saved
  in chunks, each its own transaction, so the write lock is held for about
  100 ms at a time instead of the whole edit.
- Undoing a bulk edit works the same way: over the set, a chunk at a time
  (200 records in 0.2 s instead of 10 s; 50,000 in about 40 s). Conflicts and
  refused values are left and reported as before.
- Dates in the web app follow one pattern, DD/MM/YYYY by default, chosen in
  Settings, Appearance.
- Documentation: `CLAUDE.md` is cut to the rules and traps, and there are design
  and measurement notes for billion-row collections and for the partitioning.
- `civex.rows_to_records` can match rows to existing records by a key
  (`match_on`, defaulting to the kind's first unique key), so running a workflow
  again on the same table updates or leaves records alone instead of making
  them twice. Outputs are `created`, `updated`, `unchanged` and `skipped`;
  `civex.upsert_records` runs the same code.
- Replaying an audit entry whose id already exists (push, feed pull, backfill,
  concurrent replays) stays idempotent on the partitioned `audit_log`; PostgreSQL
  tests now cover it. No behaviour change.
- New records, history entries and file references get time-ordered ids
  instead of random ones, which keeps inserts fast once the id indexes outgrow
  memory (3-4x the insert rate and 3x less WAL at 5M rows, more at larger
  sizes). Existing ids are unchanged, and the first 8 characters of an id
  (the short id civex prints and accepts) stay as distinct as before: the ids
  are a UUIDv8 with a wrapping microsecond clock first, not UUIDv7, whose first
  8 characters would be the same for every row made in a minute.

- `civex.db.migrate.schema_status(engine)` reports whether a database is at
  this civex's head, behind it, or from a newer civex, without migrating,
  stamping or locking anything. It uses one connection and one read of
  `alembic_version` (head is computed once per process), and examines
  whichever schema the engine's connections default to, so a host routing
  tenants with a PostgreSQL `search_path` can ask about each one cheaply, for
  example to report a fleet's state before a release or to refuse a stale
  tenant. Part of the public surface for hosts, with `ensure_schema_current`
  and `missing_structure`. `civex db status` and `civex serve`'s pre-flight
  use it too.

### Added

- `Permissions.denied` and `Permissions.without(actions, collections)` refuse
  an action in named collections even where the role allows it project-wide, so
  a host can say "write everywhere except these" and collections made later are
  not left out. `can` and `require` honour it.
- Record lists page by cursor as well as by offset: `cursor` / `next_cursor`
  on every records list, sorted or not, searched or not. A deep page costs what
  the first does, and records added or removed while paging neither repeat nor
  skip. `offset` still works. Exports of sorted lists no longer page by OFFSET.
- `estimate=true` on record lists and on the new `/records/count` and
  `/collections/{name}/records/count` endpoints answers totals from the
  PostgreSQL planner (no scan), reporting whether the figure is estimated;
  exact elsewhere.
- Three features name what touches the server's own machine, so a host serving
  many projects can leave them out instead of blocking routes by hand:
  `server_path_export` (exports written to a folder on the server: `POST
  /bundle/save`, `/file-access/export`, `/file-access/exports`,
  `/file-access/exports/remove`, `/releases/{name}/files/export`, `/releases/{name}/save`),
  `plugin_install` (installing plugins and workflow definitions from an imported
  bundle) and `remote_dial` (the `/remote` routes that connect out to another
  civex: connect, sync, the library; the authority routes for devices that
  connect in stay). All three are in `LOCAL_FEATURES`: `civex serve` and the CLI behave as
  before.
- Without `plugin_install`, `POST /bundle/import` still reads in schemas,
  collections, records and files, but writes no plugin and no workflow; the
  answer's new `plugins_dropped` and `workflows_dropped` say how many were left
  out. `GET /bundle` and the other downloads already stream to the client with no
  server path, and stay available everywhere.
- A service hosting many projects can give a `Project` a `read_engine` (a read
  replica's engine). Routes that only read and tolerate a replica's lag (listing
  and getting records and collections, searching, counts, record summaries and
  points, the CSV export of a collection, a view preview, record counts and
  growth in analytics) are answered from it, in a read-only transaction.
  Everything else uses the primary. `Project.needs_primary` (or
  `request.state.needs_primary`) keeps one request on the primary. Unset, and
  always on SQLite, nothing changes.
- `civex.usage.project_usage(engine)`: a public, read-only, bounded-cost
  measure of a project for a host that meters many of them. It returns stored
  bytes and files (each file counted once however many drives hold it) and a
  record count: exact on SQLite, the planner's estimate on PostgreSQL (a
  capped count if the table was never analysed). It honours the engine's
  `search_path`, runs under a statement timeout, and reports a figure it could
  not measure as `None`.

## v2.0.1 — updating right after a release, a quicker desktop app (2026-11-19)

No database migrations.

### Fixes

- Updating to a release in the first few minutes after it was published
  failed with "only civex[desktop]<=2.0.0rc15 is available". The update check
  asks PyPI directly, so it saw the new release at once, but uv installed from
  its own copy of the package list, which it keeps for up to ten minutes. Both
  `civex update` and the desktop app now have uv fetch a fresh list for civex
  before installing.
- In the desktop app, **Open project** or **New project** from inside a
  project left the first project's server running. Its background work (sync,
  file moves) then ran against the folder of the project opened next. The
  window now runs one project at a time and stops the previous one first.
- The desktop app's "couldn't open this project" page no longer suggests
  `pip install`. It names the log file and `civex doctor`, and has a way back
  to the start screen.

### Changes

- **Back to the start screen.** In the desktop app, **Project ▸ Start screen**
  returns to opening, creating and recent projects without restarting the app.
- **A quicker desktop app.** The launcher no longer starts civex just to ask its
  version each time the app opens (it reads it from the installed package,
  saving a second or more). Opening a project from the start screen takes about
  0.4 s instead of 2 s, because the server's code loads while the start screen
  waits. Switching between projects takes about 0.3 s.
- Stopping a server (closing the desktop app, switching project, Ctrl+C on
  `civex serve`) no longer waits up to two seconds for the sync worker.
- The install guide says `uv tool install --force "civex[desktop]"`, as the
  command line does, for adding the desktop window to a civex installed with uv.

## v2.0.0 — sync between machines, a workflow builder, files on drives or in a bucket (2026-11-18)

civex 2.0 lets a project be kept on several computers through one server.
Workflows can be built in a form without knowing YAML, files can live in an S3
bucket, exports and file moves ask fewer questions, and the desktop app installs
and updates itself. This entry covers everything since v1.2.0, including what
the release candidates (2.0.0rc1 to rc15) carried. If you are upgrading, read
**Breaking** first.

### Breaking

- **Database migrations.** They all run by themselves when a project is first
  opened, and existing data is kept. If you upgrade a SQLite project by hand,
  have about its size free on the disk, because `records` is rebuilt
  (`c4d8e2f6a9b3`). The migrations, in order of area:
  - sync: `c9e1f4a7b3d2` (sync tables, `audit_log.apply_state`),
    `d6c2a8f41b07` (conflict context), `a8c4e2f6b1d9` (device keys),
    `c1e8f4a2b7d3` (join requests), `b5e1d8f2a647` (which device a change came
    through), `a7c3e9f1b5d2` and `d2f6a9c4e8b1` (which files the server has
    and lacks), `b2d6f8a3c517` and `e6a2c8f4d1b7` (the shared library and its
    versions);
  - history: `e8b4f2c6a917` (entries that store only what changed, written in
    order), `f1c3a5e7b902` (one action's entries kept together),
    `a4d9e2c7f310` (an index for converting old history);
  - files: `c3f7a9e1d5b8` (a file may have copies on several drives),
    `f7b3d9e2a6c4` (each record's file points at one copy), `b9d4e7f2a1c6`
    (when a copy was checked against its hash);
  - exports: `d9f3b1c7e4a2`, `e1a7c5b8f204`, `f4b8d2a6c139`, `a1e5c9d3f7b2`
    (saved exports, their tables and how they are handed over),
    `c8e2a4f6d913` (a view's file layout);
  - records: `b3c7d1e9f5a2` drops each collection's schema list (see below),
    `c4d8e2f6a9b3` checks a record's parent and collection at commit, and
    `bc183bbafef8` turns a lone file stored in a `file_list` field into a list
    of one.

  History written by v1.2.0 and earlier is converted to the new compact form
  in the background after the server starts. `civex history compact
  [--vacuum]` converts it straight away.
- **A collection holds records of every schema.** The schema checklist is gone
  from the collection forms, from the CLI (`--schema` on `collection
  create|update`, and `collection add-schema`) and from the API. Migration
  `b3c7d1e9f5a2` drops the `dataset_schemas` table and every list in it. A
  schema made after a collection can be used in it at once.
- **`civex dump`/`civex restore` are replaced by bundles** (see *Records and
  schemas*). `GET /dump` and `POST /restore` are gone. To read a YAML dump
  from an older release, use that release.
- **The guided import is gone.** This was the spreadsheet and folder wizard
  under **New ▸ Import data…** and a schema page's **Import data**. Add
  records from the **New** menu. To bring in a folder of files, use a workflow
  (`civex.create_records_from_files`, `civex.match_files_to_records`). The
  workflow builder has starting points for both.
- **A workflow run that fails keeps none of its writes.** A run happens
  inside a savepoint and is committed once with its outcome. If a step fails,
  every record change the run made is undone. Before, it kept what the steps
  before the failure had written. A run you stop on purpose still keeps what
  it got through. `ctx.commit()` now does nothing and warns.
- **Plugins need `civex-plugin-sdk` 0.3** (`>=0.3.0,<0.4`; wire protocol 3).
  civex still runs plugins written for protocols 1 and 2. Built-in plugins
  now run through the same protocol, so an error from one arrives as a
  `PluginExecutionError`; its kind (`validation_error`, ...) is kept. A
  plugin's process is now kept between runs, so state at module level lasts
  from one run to the next. See *Workflows and plugins*.
- **Values are checked more strictly**, wherever they are written (the app,
  the CLI, `civex.open()`, workflows and sync):
  - An `integer` or `float` field refuses anything that isn't a number, even
    with no restrictions. It used to store `"deep"`. `civex.upsert_records`
    now reports such a cell as a skipped row.
  - A `file_list` field refuses a lone file, a `file` field refuses a list,
    and neither takes a value that isn't a stored file. Migration
    `bc183bbafef8` repairs values already stored.
  - On a `file_list` field, `civex.match_files_to_records` now **adds** the
    file to the list instead of replacing it.
  - A `field=value` filter without a schema raises `ValidationError`. It used
    to match nothing.
  - A file field's name template is the file's stem, and the file always
    keeps its own extension. `{ext}` is refused, and a trailing `.{ext}` is
    dropped when the template is saved. Older templates still render.
- **Exports and file moves:**
  - The `files_scattered` answer (409) and `FilesScatteredError` are gone,
    because an export folder is now always made (see *Exports*).
  - Files in an **Open as a folder** export that are linked to the stored
    file are read-only.
  - The *grouped* layout is no longer offered. Exports and views saved with it
    still run.
  - `civex files gather --include-shared` is a hidden no-op: every picked
    file moves.
- **The desktop app is a launcher** that installs civex the first time it
  starts (see *Desktop app and updates*). The `civex-desktop` command is gone;
  `civex desktop` opens the window from a terminal.

### Added: sync between machines

- **A project can follow a server** (an *authority*: any `civex serve` with
  serving turned on). Changes merge field by field. When two people change
  the same value, the server's value stays and yours is kept for review. A
  retry is safe and a dropped connection resumes. The commands are
  `civex sync …` and `civex clone`, the app has Settings → Sync, and the
  Syncing guide walks through it.
- **Sync runs by itself** while the server is up, and with `civex sync
  watch`: after changes, on an interval, and backing off while the server
  can't be reached. The status bar shows a sync that is running, failing or
  waiting for review. Failures are said in plain words; the technical text
  is in the log and behind *Technical details*.
- **Running a server for other devices:** `civex sync authority enable`.
  Other machines reach only `/api/sync/v1/`. `civex serve --sync-only` serves
  just that, for a server behind an HTTPS proxy. Devices connect over
  `https://` only (`http://` only to this computer), or over **`ssh://`**:
  the far machine runs `civex sync ssh-serve` through your own SSH login, and
  nothing stays running there between syncs.
- **Devices join by invite or by asking.**
  - An invite (`civex sync device invite <name>`, starting `civex_inv_`)
    works once and expires after 24 hours by default.
  - A device can instead ask to join. It shows a code, which an admin
    approves with `civex sync device approve`, or under Settings → Sync →
    *Asking to join*.
  - Either way, the device makes its own Ed25519 key, which never leaves it,
    and signs in with it for a session of a few minutes. A different server at
    the same address is refused before anything is sent.
  - `civex sync device list|cancel|revoke`. Revoking takes effect at once.
- **Reviewing what didn't go in.** A clash, a refused change or an edit that
  met a delete is settled on the record's own **Resolve** tab:
  - Their value is on one side and yours on the other, the differences are
    marked, and the middle is the usual input. You can also type a value of
    your own.
  - **Start review** steps through every record waiting.
  - `/sync/review` lists them, with **Keep theirs for all** and **Undo**.
  - A refused record shows the field to fix, and fixing it sends it. **Send
    again** waits for the server's answer.
  - The same is available from `civex sync conflicts|resolve|reopen`.
- **History says who and through what.** A synced change keeps who made it
  and which device sent it ("l2 via backup"). The author's name is set per
  project with `civex sync user` or in Settings → Sync.
- **Files sync separately from records**, in the background, so a sync takes
  seconds however much the files weigh.
  - The status bar shows files going up (bytes, speed, time left), offers
    **Send now** when some can go, and lists *missing* files (on no drive here
    and not on the server) separately, naming the computer that added them.
  - Each collection keeps its files on this computer or fetches them when
    they are opened. **Free up space** removes this computer's copies of files
    the server holds. Commands: `civex sync files|keep|free|fetch|send`, or
    Settings → Storage → Collections.
  - **Their files** filters by *On the server* and *Not on the server yet*.
- **Shared workflows and plugins.** A person publishes and others install;
  they are never synced as they change. Every version is kept, and a workflow
  pins the plugin versions it was published with. An install is checked
  against the workflows already here first, and plugin code is shown and must
  be trusted before it is installed. Devices may publish only once allowed
  (`civex sync device allow-publish`), and the server accepts plugins only
  with `[sync] library = all`. Commands: `civex sync library
  list|show|publish|install|remove`. In the app it is part of the Workflows
  page.
- **Versions are shown, not enforced.** Settings → Sync and `civex sync
  status` show which civex each side runs. Whether two machines can sync is
  decided by the sync protocol (3) alone, so updating the server doesn't cut
  devices off. A server that will stop accepting an older civex says so first
  (*Update civex soon*).
- A project either serves devices or follows a server, never both.
- A device that fell behind a server whose history was pruned copies the
  project again instead of skipping changes. A first copy shows its progress
  and fetches history afterwards in the background.

### Added: files and storage

- **Files in an S3 bucket** (or MinIO and the like), in every install. Set
  `[store.s3]` in `config.toml`, or use Settings → Storage → Tasks → **Use a
  bucket…** or `civex store bucket check|set|show|clear`.
  - The bucket is tried first.
  - A project switches only while the place it leaves holds none of its
    files.
  - Credentials come from the environment or an AWS profile, never from
    `config.toml`.
  - Where the bucket allows it, uploads and downloads go straight to it by
    presigned URL, for the app and for syncing devices (`direct = false` turns
    this off).
- **A file may have copies on several drives, and each record's file points
  at exactly one.** Where a record's file is, what a drive holds and what a
  move frees are now facts instead of a pick among copies. A move copies only
  what isn't on the target already. Clean-up removes only copies nothing
  points at.
- **Their files**: the records explorer can show the files of the records it
  lists, and everything beneath them, using the same filter. You can filter
  by place and by kind of file, tick files, and **Move to drive…**,
  **Download** or **Free up** the files. A record page links to it too, and
  `/collections` gets an **All records** tab covering every collection.
- **Adding files goes in batches** (`PUT /files/batch`), so 300 files are a
  few requests. If one file fails, what went in is kept and you are offered
  the rest. A file and its record save as one request: if the record is
  refused, the new file is removed.
- File moves show each stage while they are prepared, count files already on
  the target as "already there", and are described in one sentence ("Moves 3
  files (3.0 KB) onto archive, and frees 2.0 KB on other drives").

### Added: exports

- **Saved exports** start from a schema and take its records and everything
  inside them. Each export is a page of its own on the new **Exports** page
  (`/exports`). They are managed there, and from `civex schema exports …` and
  `civex files list|export|gather --export`. An export is saved with how it
  is handed over (**Open as a folder**, **Put on a drive** or **Download as a
  zip**), so running one from any Export menu needs no dialog.
- **Tables beside the files, or instead of them**, in csv, tsv, xlsx, json or
  jsonl: one of every record, one per folder of a kind, or a record's own
  details sheet, with your choice of name and columns. The preview shows each
  table in the folder it will be written to.
- **Open as a folder always makes one folder.** Files that can be linked are
  linked, and the others are copied after checking there is room, so files
  spread over several drives no longer stop an export. The editor has two
  steps (What, then Finish), and a **Put all the files in one folder** box
  next to the live preview. Files that can't be reached are listed before you
  start. An export started from a list begins as just that list's table.

### Added: workflows and plugins

- **A workflow builder.** **New workflow** offers starting points (fill a
  field from a file's name, put files on matching records, records from a
  table, and more) and opens a form.
  - Each step is chosen by name, and its settings are lists of your own
    fields and schemas.
  - Each step is said as a sentence filled in with what you chose.
  - **YAML** switches to the file and back, keeping its comments.
- **Patterns from an example.** Click the parts of a real file name instead
  of writing a regular expression. Every name is shown with the value it
  gives.
- **Live preview.** What is on screen runs, saved or not, on the five records
  of its kind changed most recently, about half a second after each edit.
  Nothing is kept (`POST /workflows/try-many`).
- **On and off.** A workflow made in the app starts off. **Turn it on** once
  the preview fails on none of its records, or use `civex workflow
  enable|disable`.
- **Each workflow has a page** (`/workflows/<name>`) with Overview, Sharing
  and Preview tabs. The Workflows page is one list (search, filter by sharing,
  sort).
- **Fields filled from a file's name when the record is saved.** A text,
  number, date or datetime field can carry a rule (Rules → **Filled from file
  name**, or `--from-file FIELD --filename-pattern PATTERN`). A pattern such
  as `DDMMYYYY_HHmmSS` fills the field before validation, so it can be part of
  a unique key.
- **Plugins:**
  - A plugin's `print()`s and stderr reach the run's log.
    `ctx.progress(done, total, message)` shows in the status bar.
  - Files go to plugins by path, in one folder per run (`ctx.file_path`,
    `ctx.store_path`, `ctx.run_dir`; `CIVEX_RUNS_DIR` moves it) instead of
    base64.
  - A plugin's contract is written into its header (`[tool.civex]`, `civex
    plugin check --write`), so discovery doesn't need to run it.
  - A plugin's dependencies are locked the first time it starts
    (`<plugin>.py.lock`), so updating civex no longer rebuilds every plugin.
  - Capabilities are permission actions (`read`, `write_records`,
    `manage_files`, `delete`).
  - The new `ctx.patch_record` changes only the fields given.
- **Runs:** delete runs, whether waiting, running or finished (`POST
  /jobs/delete`, `civex automation delete`, **Delete N…**). Ticking a page of
  runs offers **Select all N matching**. The status bar shows the step a run
  is on.

### Added: records, schemas and history

- **Bundles** move a project's data to another project: `civex bundle
  export|show|import`, `GET /bundle`, `POST /bundle/import`, and **Export
  bundle…** / **Import bundle…** on the Collections page.
  - A bundle is a zip of schemas, collections, records (ids kept, so nesting
    and references survive), and optionally files, workflows and plugins.
  - Importing matches schemas and collections by name and records by id, so
    the same bundle can be imported again.
  - Every record goes through the usual checks and history, and the import is
    one event in Activity.
- **Moving records** to another collection, or inside another record there:
  **Move to…** on the explorer's selection bar, `civex record move|move-all`,
  `POST /records/move`. A record keeps its id, values and history and takes
  everything beneath it. The move is refused whole if a reference would break,
  a uniqueness key is taken, or the kind can't sit there.
- **History stores only what changed** in an edit. A large history takes a
  fraction of the space, and Settings → Database → *History storage* can
  reclaim the space freed (SQLite).
- **Records under a deleted record** are found and can be put back (`civex
  record orphans|restore-above`, Settings → Database, a banner on the record
  page). `civex doctor` counts them.
- **The Python API:** `civex.open(path)` opens a project in your own process,
  with the same services the CLI and server use and no server needed.
  `with civex.open(...) as project:` commits on success and rolls back on an
  error. See Guides › Running civex › From Python.
- **Download names from the records above.** A file's name template can use
  fields of the records above it and reach through a reference
  (`{species.common}_{site}_{take:02}`). Values are inserted from a searchable
  list.
- **The schema page is simpler.**
  - Fields are wide rows that open in place.
  - **Add field** shows the kinds as large cards.
  - Only the kind's main rule shows inline; the rest is behind **More rules**.
  - The app calls the two names **Name** and **Key**.
  - Naming and Uniqueness are one **Records** tab.
  - Every record form ends with **+ Add field**.
- **Starting a collection** is a short guide with its own **New schema…**
  button.
- File columns in the records table show the file's name and size, not JSON.
- The docs open with one page on schemas, records and collections, use one
  survey example (Site › Visit › Sample) throughout, and have a new How-to
  section. The AI assistant explains things the same way, and proposes a
  record when someone describes one thing rather than a kind of thing.

### Added: desktop app and updates

- **Update from the app** (Settings → Updates, and a notice in the status bar):
  - civex closes, installs the new version and starts again.
  - This works for the desktop app and for `civex serve` installed with uv,
    pipx or pip (`GET`/`POST /api/update`).
  - Other servers running from the same copy are stopped and started again,
    after asking.
  - `civex update --pre`, or *Include pre-releases*, installs release
    candidates.
- **Settings → Logs and `civex logs`** collect every log civex keeps on this
  computer in one place.
- **Size** in Settings → Appearance (80% to 125%). In the desktop app, ⌘/Ctrl
  with + − 0 changes it too.
- A database from a newer civex is explained (what it is and what to do)
  instead of failing every request. `civex serve` refuses to start on one.

### Added: for hosts and developers

- **One project per request:** a server serves the project it is asked for
  (`deps.current_project`, `app.state.project_resolver`). Settings are saved
  through a `ConfigStore`. Background jobs open contexts through a factory.
- **Features** (`domain/features.py`, `GET /api/status/features`): a host
  that offers less leaves those routes out, answers 501 in plain words, and
  the app hides what isn't there.
- **Permissions** (`domain/permissions.py`, `GET /api/me`): read, write
  records, change the structure, add files, delete, and manage members,
  everywhere or in named collections. The services refuse with a 403, and the
  app switches off the controls you may not use and says why. A project in a
  folder allows everything, as before.
- **Served under a path** (`/p/<owner>/<project>/`): the page's `<base
  href>`, a boot object, five extension slots and `@civex/ui`.
- **`civex.testing`** ships the sync harness, including the convergence and
  invariants scenarios, a test server and a fake bucket. CI gains a PostgreSQL
  job, and real v1.1.4 and v1.2.0 databases are upgraded in the tests.
- The store protocol is split into `ObjectStore` and `VolumeStore`.
- `benchmarks/` has a data generator and a stress test.

### Changed

- **The desktop app is a small launcher** (about 30 MB) that installs civex
  with its own uv onto Python 3.13 the first time it starts, then keeps it up
  to date.
  - Windows gets an installer (`civex-<version>-windows-setup.exe`) with a
    Start menu entry, an uninstaller, and an optional `civex` command on PATH.
  - macOS gets one disk image for Intel and Apple silicon. Neither is signed
    yet; the install guide says how to open them.
  - The window fits the screen and opens as you left it.
  - Downloads open the system's Save dialog. F5, Ctrl/Cmd+R and back/forward
    keys work.
  - No terminal or console windows open, including for plugin processes.
- **Install with `uv tool install civex`**, which needs no Python on the
  computer.
- **The app says "drive", never "volume"** (Settings → Storage → **Drives**).
  The CLI and the code keep "volume".
- **HTTPS trusts what the operating system trusts** (`truststore`), for sync
  and the update check. This includes a company's own certificates.
- The window never scrolls as a whole, and menus stay inside it.
- Explanations moved into tooltips across the app.
- New dependencies: `cryptography` (48 on Intel Macs, the last version with
  builds for them), `truststore`, `openpyxl` and `boto3`. Notable upgrades:
  SQLAlchemy 2.1, FastAPI 0.162, pandas 3.1, pydantic 2.14, React 19.3. Other
  dependencies were updated for security advisories (certifi, virtualenv,
  mako, msgpack, filelock, minimatch, vite, vitest).

### Fixes

- **Reordering a schema's fields, and the name templates a field rename or
  delete rewrites, now appear in history.** A new test checks that the latest
  history entry about each schema, field, collection, view and record matches
  the database.
- "Their files" and the move preview are up to 5× faster on large projects
  (17k records: 9.9 s to 1.9 s for a move preview).
- Dialogs are readable in dark mode, and native controls draw dark.
- What the desktop app's pages remember (pins, recent items, dismissed
  notices) lasts from one opening to the next.
- The Windows desktop app has its project menu and native folder picker.
- The page no longer freezes after using the navigation drawer in a narrow
  window.
- `civex update` in a terminal updates the desktop app's copy, and repairs no
  longer pin the version.
- Including pre-releases no longer installs pre-releases of civex's own
  dependencies.
- A plugin that writes a lot to stderr no longer hangs.
- A record page with a lone file in a `file_list` field no longer fails with
  "c.filter is not a function".

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
