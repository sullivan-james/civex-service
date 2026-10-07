# Server & web UI

## Starting the server

```bash
civex serve                  # production mode — serves built UI from frontend/dist/
civex serve --reload         # development mode — auto-restarts on code changes
civex serve --host 0.0.0.0   # listen on all interfaces (see Security model below)
civex serve --port 9000      # custom port (default: 8000)
civex serve --log-level DEBUG  # DEBUG | INFO | WARNING | ERROR — see Logging & telemetry
```

The server must be run from within (or below) a directory that contains a `_civex/` project.

## Security model

`civex serve` is **local-first, like `git`** — it runs for a single trusted user on your own machine and has **no authentication**. By default it binds to loopback (`127.0.0.1`) and a middleware guards the two attack classes that still apply to a localhost server open in a browser:

- **DNS rebinding** — requests whose `Host` header isn't a loopback name are rejected.
- **CSRF** — state-changing requests (`POST`/`PUT`/`PATCH`/`DELETE`) carrying a non-loopback `Origin` are rejected.

Passing a non-loopback `--host` (e.g. `0.0.0.0`) without opting in exits immediately with an error and does not start the server:

```bash
civex serve --host 0.0.0.0
# Refusing to bind to non-loopback address '0.0.0.0': the civex server has no
# authentication and would be reachable by other machines.
# Re-run with --allow-remote if this is intentional (and put it behind a
# reverse proxy / firewall).
```

To expose the server to other machines you must opt in explicitly:

```bash
civex serve --host 0.0.0.0 --allow-remote
```

`--allow-remote` stands the guard down and prints a warning instead of exiting. Because there is still no authentication, only do this on a trusted network **behind a reverse proxy or firewall**.

For other civex installs to sync with this project, don't expose the app: serve them with `civex serve --sync-only` (see [Syncing between machines](sync.md#set-up-the-authority)).

## Web UI

Opening [http://localhost:8000](http://localhost:8000) (or wherever you configured it) loads the web interface. The main sections are:

**Schemas** — Create and edit schemas, add and configure fields, view field types and restrictions.

**Collections** — Create collections and browse their records top-down through the schema hierarchy, with search, filters, saved filters ([views](views.md)), columns, sort and export. The collections you open most appear under **Collections** in the left-hand navigation. See [Browsing a collection](collections-and-records.md#browsing-a-collection).

**Selecting several** — In any table with tick boxes, and in the lists of columns, schemas and shape types, click one box and then **shift-click** another to tick (or untick) everything between them, in the order shown. The next range starts from the box you last clicked.

**Tab titles** — The browser tab says where you are, so several open tabs can be told apart: a record shows its name, then the record it sits under and its collection ("Sample 12 · Patient 3 · study"), a settings page shows its area ("Tasks · Storage · Settings"), and everything ends with "civex".

**Records** — Each record has a detail page showing its field values, attached files, everything under it (children, grandchildren, … in the same explorer), workflow jobs that have run against it, and a form to edit field values.

- File fields show a file picker for upload and a download link for existing attachments.
- `datetime` fields display and edit in the collection's timezone (or the field's own override), with the zone shown next to the value and the UTC value on hover. If neither is set they use your own timezone. Values are stored as UTC.
- `reference` fields show a searchable dropdown of records from the target schema.
- String fields with a `choices` restriction render as a dropdown.
- A **"⊙ from filename"** button appears on text/number/date/datetime fields whenever a file field on the same record has a file attached — lets you extract a value from the filename using a regex, without writing a workflow.

**Runs** — A paginated log of all workflow job executions, filterable by status (`pending`, `running`, `completed`, `failed`). Each job shows its log output.

**Workflows** — View and edit workflow YAML files directly in the browser. Run a workflow manually with the **Run** button on a record's detail page.

### Pins, Home and jump-to

Click the star on a saved filter, a collection, a record or a drilled-down place in the explorer to **pin** it. Pins appear in a **Pinned** section at the top of the left-hand navigation; a pinned saved filter shows how many records it matches right now. Pins and the list of things you opened lately are kept in your browser (they don't follow you to another machine or browser profile, and clearing site data removes them).

**Home** shows your pinned saved filters with their live counts under *Needs your attention*, and what you opened lately under *Pick up where you left off*, each with a star to pin it.

Press **Ctrl+K** (**⌘K** on a Mac), or click **Jump to** in the top bar, to search collections, schemas, saved filters, records and places by name. Records are searched across every collection in one go, and each result shows which collection it is in. With nothing typed it lists your pins and recents. The star on a result pins it.

## HTTP API

Everything the web UI does, it does through `/api/` — schemas, collections (`/api/collections`), records, files, workflows, and jobs. Responses are JSON. For the complete, current list of endpoints, use the interactive documentation (Swagger UI) at [`/docs`](http://localhost:8000/docs) while the server is running, rather than a table here that would drift from the code.

Two examples worth calling out because they're the ones you're likely to script against directly:

```bash
# Upload a file, then use the returned sha256 as a `file` field's value
curl -X POST http://localhost:8000/api/files \
  -F "file=@/path/to/recording.wav"
# → {"sha256": "abc123…", "filename": "recording.wav", "size": 4096000}

# Run a workflow against a record (multipart if it declares `files` inputs)
curl -X POST http://localhost:8000/api/workflows/extract-start-time/run \
  -H "Content-Type: application/json" \
  -d '{"record_id": "abc123…"}'
```
