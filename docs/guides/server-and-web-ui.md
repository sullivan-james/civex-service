# Server & web UI

`civex serve` starts civex's web app and HTTP API for the project you're in. It
runs on your own computer, for you, like `git`: there are no accounts or
passwords.

## Start it

From inside a project (any folder at or below the one holding `_civex/`):

```bash
civex serve --open
```

This starts the server at [http://localhost:8000](http://localhost:8000) and
opens it in your browser. Stop it with **Ctrl+C**.

To start it with a double-click instead, run `civex shortcut` once: it puts a
shortcut for this project on your Desktop.

## Who can reach it

By default only this computer can. Pick the row that matches what you want:

| You want… | Do this |
| --- | --- |
| To use civex yourself, on this computer | `civex serve` (the default) |
| Other computers to **sync** with this project | `civex serve --sync-only`, reached over HTTPS: see [Sync a project between computers](../how-to/set-up-sync.md) |
| To use this computer's civex **from another computer** | Forward the port over SSH: `ssh -L 8000:localhost:8000 <this computer>`, then open `http://localhost:8000` there |

Sharing the web app itself on a network isn't supported: it has no sign-in, so
anyone who could reach it could read and change everything, and run workflows.
`--allow-remote` (below) exists for setups that put their own protection in
front, and civex prints a warning when it's used.

??? note "What protects the default"
    The server listens on `127.0.0.1` only, so other computers can't connect at
    all. It also refuses requests that don't come from this computer's own
    pages: a `Host` header that isn't `localhost` (DNS rebinding) and a change
    sent from another site (`Origin`, cross-site request forgery).

## The web UI

The left-hand navigation has:

| Section | What it's for | More |
| --- | --- | --- |
| **Home** | Your pinned saved filters with live counts, and what you opened lately | |
| **Collections** | Browse and edit records, their files and everything under them; search, filter, save views, export | [Collections & records](collections-and-records.md), [Views](views.md) |
| **Exports** | Saved exports, and the folders they've made | [Exports](exports.md) |
| **Activity** | Every change, who made it, and restoring what was deleted | [Deleting & restoring](deleting-and-restoring.md) |
| **Schemas** | The kinds of record, their fields and rules | [Schemas & fields](schemas-and-fields.md) |
| **Workflows**, **Runs** | Automations and each time one ran | [Workflows](workflows.md), [Automation](automation.md) |
| **Settings** | Appearance, database, storage, retention, sync, map | |

A few things work everywhere:

- **Ctrl+K** (**⌘K** on a Mac) jumps to any collection, schema, saved filter or
  record by name.
- **The star** pins a collection, record, saved filter or place to the top of
  the navigation. Pins and recent items are kept in this browser only.
- **Shift-click** a second tick box to tick everything between it and the last
  one you clicked.
- **The status bar** at the bottom shows work going on in the background (file
  moves, workflow runs, sync) and anything that needs you.

## HTTP API

Everything the web UI does goes through `/api/`, as JSON. The full, current
list of endpoints is at [`/docs`](http://localhost:8000/docs) while the server
runs. Two you're likely to script against:

```bash
# Upload a file; use the returned sha256 as a file field's value
curl -X POST http://localhost:8000/api/files -F "file=@recording.wav"
# → {"sha256": "abc123…", "filename": "recording.wav", "size": 4096000}

# Run a workflow against a record
curl -X POST http://localhost:8000/api/workflows/extract-start-time/run \
  -H "Content-Type: application/json" \
  -d '{"record_id": "abc123…"}'
```

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `--open` | off | Open the browser once the server is up (or just open it, if civex is already running on that port) |
| `--port`, `-p` | `8000` | The port to listen on |
| `--sync-only` | off | Serve only what syncing devices call; see [Syncing between machines](sync.md) |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`; see [Logging & telemetry](logging-and-telemetry.md) |
| `--host` | `127.0.0.1` | The address to listen on. Anything but this computer's own is refused without `--allow-remote` |
| `--allow-remote` | off | Allow `--host` to be a network address. There is no sign-in: only behind protection of your own |
| `--reload` | off | Restart when civex's own code changes, for working on civex itself |
