# Logging & telemetry

civex writes **structured logs** locally and can optionally send **crash reports** to an error-tracking service. The two are separate:

- **Logging** — a local record of what happened. On by default. Stays on your machine.
- **Telemetry** — crash reports sent off your machine so the maintainer can see errors across installs. **Off by default**, opt-in only.

## Logging (default)

When you run `civex serve`, logs go to two places:

- **Console** — human-readable, colored output when attached to a terminal; single-line JSON when piped or captured.
- **File** — rotating JSON lines at `_civex/logs/civex.log` (5 MB × 3 backups), ideal for grepping or shipping to a log tool.

Every HTTP request gets a correlation id (returned in the `X-Request-ID` response header and attached to every log line for that request). Values that look like credentials (`api_key`, `token`, `authorization`, `password`, …) are automatically redacted to `***` before anything is written. The `_civex/logs/` directory is git-ignored.

Set the level from the CLI (overrides config):

```bash
civex serve --log-level DEBUG      # DEBUG | INFO | WARNING | ERROR
```

Or configure it in `_civex/config.toml`:

```toml
[logging]
level = "INFO"          # default INFO
json_console = false    # omit for auto (color on a TTY, JSON otherwise)
to_file = true          # write _civex/logs/civex.log
```

## Every log in one place

civex keeps a few logs besides the project's, each where the thing that writes
it can put it:

| Log | What writes it |
|---|---|
| `project` | This project's server (`_civex/logs/civex.log`) |
| `desktop` | The desktop app's window |
| `launcher` | The desktop app's launcher: installing and updating civex |
| `update` | Updates of a `civex serve`, run after it closed |
| `serve-<port>` | A server an update stopped and started again (off Windows) |

**Settings → Logs** shows them all: the latest lines, newest first, with a
level filter and search, **Follow** for new lines, **Download**, and **Open
folder**. Anything in the app that mentions a log links there (a failed update,
a sync that can't reach its server). A workflow run's log is on the run's own
page.

From a terminal:

```bash
civex logs list                         # which there are, and where
civex logs show                         # the project's latest 50 lines
civex logs show launcher -n 200         # another log
civex logs show --level error -f        # errors only, and keep following
civex logs path update                  # where it is
civex logs open                         # its folder in the file manager
```

The project's log is JSON lines, so other tools read it too:

```bash
cat _civex/logs/civex.log | jq 'select(.level == "error")'   # errors only
```

## Error responses

Expected errors (not found, validation, conflicts) return a clear message and the right HTTP status. Unexpected server errors return a **generic** `500 {"detail": "Internal server error", "request_id": "..."}` — the full traceback is written to the logs only, never leaked to the client. Quote the `request_id` when reporting a problem to find the matching log line.

## Telemetry (opt-in crash reporting)

Nothing is sent off your machine unless you turn this on. It uses [Sentry](https://sentry.io) and reports only exception stack traces (no request bodies, `send_default_pii=False`, no performance tracing).

1. Nothing to install — the Sentry SDK ships with civex.

2. Provide a DSN — either in `_civex/config.toml`:

   ```toml
   [telemetry]
   dsn = "https://<key>@<org>.ingest.sentry.io/<project>"
   environment = "local"
   ```

   or via an environment variable (takes effect without editing config):

   ```bash
   export CIVEX_SENTRY_DSN="https://<key>@<org>.ingest.sentry.io/<project>"
   ```

With no DSN (the default), telemetry is a no-op even though the SDK is installed.
