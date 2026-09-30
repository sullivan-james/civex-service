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

Inspect the log file directly:

```bash
tail -f _civex/logs/civex.log
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
