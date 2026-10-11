# Architecture

```
civex-service/
  src/civex/
    cli/           # Typer commands — thin: parse args → call service → format output
    plugins/       # Plugin contract (BasePlugin, WorkflowContext) + built-ins + registry
    workflows/     # YAML definition models + topological executor
    services/      # Business logic: SchemaService, DatasetService, RecordService, FileService
    repositories/  # Protocol interfaces + SQLAlchemy implementations
    domain/        # Plain dataclasses (DTOs) and exceptions — no framework dependency
    db/            # SQLAlchemy models and session factory
    server/        # FastAPI app, routers, and static frontend assets
    config.py      # Project root discovery + config loading
    context.py     # AppContext factory (wires all repos + services)
```

**Sync** does not exist yet: the old push/pull was removed in 1.2.0 and is being redesigned (CIVEX-305). The plan is one authority per project that other devices sync to, with `audit_log` as the queue of changes to send. `audit_log` already has the columns it will use (`actor`, `device_id`, `hlc`, `hub_seq`, `sync_state`); only `actor` is written so far (the OS user running civex, unverified). For synced changes `actor` will be set by the authority from the authenticated caller, never by the client, and `device_id` is generated once per machine and stored outside the project folder.

**Layer rules (strict):**

- `cli` → `services` via `AppContext`. Never touches repos or DB models directly.
- `services` → `repositories/protocols` (interfaces). Never imports from `cli` or `db`.
- `repositories/local` → `db/models`. The only layer that imports SQLAlchemy models.
- `plugins` → `WorkflowContext` only. Never imports SQLAlchemy or sessions.
- `domain` has no imports from the rest of civex — it is always safe to import anywhere.

These rules exist so a layer's implementation can change — a different repository backend, a non-SQL store, a plugin that runs out-of-process — without touching the layers above it. `services` code that imported SQLAlchemy directly, for example, would break the moment a repository stopped being backed by a database.

## The `AppContext` pattern

`build_context(project)` in `context.py` is the single place that wires everything together: it builds (or takes) the SQLAlchemy engine and session, constructs every repository, and injects them into the services. A `Project` (`civex/project.py`) is what it is built from: the project's `Config`, the `ConfigStore` the settings are kept in, the `actor` changes are recorded as, and optionally a shared `engine` and `migrated=True` (the host already brought the database up to date, so the per-request schema check is skipped). `build_local_context(config)` is `build_context(Project.local(config))`: the project in a folder on this machine, kept in its `config.toml`, with changes recorded as its chosen name or the OS user. Both entry points go through it:

- CLI commands call `get_ctx()` (`cli/utils.py`), which wraps `build_local_context()`, use `ctx.<service>` to do the work, call `ctx.commit()` after mutating operations, and `ctx.close()` when done.
- The server resolves the project once per request (`server/deps.py: current_project`, the one in its working directory unless the host installed `app.state.project_resolver`) and builds a context from it, so each request gets its own session. Routes that need only the settings (`settings`, `db`, `ai`) depend on `current_project` instead of a context.

Settings are saved only through `ctx.config_store` (`ConfigStore`: `load`, `save`, and `flag` for the booleans asked on every request). `FileConfigStore` is `config.toml`; `parse_config` and `render_config` are its pure text form, so a host that keeps a project's settings elsewhere parses and renders the same text. A service never calls `save_config` itself; the database-admin paths (`db_service`, `db_move_service`) and the CLI are the exception, being the local host by definition.

What a server does is said once, in `domain/features.py`: a `Project` carries the features its host offers (everything a machine does, by default), `server/app.api_routers(features)` is the one router list every host includes from, `deps.requires(feature)` makes a route inside a shared router answer 501 in plain words, and `GET /api/status/features` tells the frontend what to hide. The background hosts (`history_jobs`, `transfer_jobs`, `sync_jobs`, `background.run_pending_jobs`) open contexts through a factory they are given, defaulting to the project in the current directory.

A command or route handler never constructs a repository or service directly — it asks `AppContext` for one, keeping the wiring in one file instead of scattered across every CLI command and router.

## Data model

Record `data` is stored as a single JSON dict per record — there is no entity-attribute-value table. On PostgreSQL, JSON columns use `JSONB` via SQLAlchemy's `with_variant` (`_JSON = JSON().with_variant(JSONB(), "postgresql")` in `db/models.py`), which gets GIN-indexable containment queries on Postgres while staying plain JSON text on SQLite — the same model code runs against both backends unchanged.

Field types: `integer | float | string | boolean | date | datetime | file | file_list | reference`.

- `file` / `file_list` — the record stores a `FileRef` dict (`{sha256, filename, size}`), or a list of them; the bytes themselves live in the content-addressed object store described above.
- `date` — stored as an ISO date string (`YYYY-MM-DD`). `datetime` — always stored as a UTC ISO string. Values with no UTC offset are read in the field's `timezone` restriction, else the collection's timezone, else UTC (`domain/timezones.py`, applied in `RecordService._normalise_datetimes`).
- `reference` — stores the UUID of another record as a string; the target schema is enforced via a `schema` restriction on the field.

Schema inheritance is resolved recursively by `SchemaService.collect_fields()` — a child schema's own fields come first, followed by each ancestor's fields (labelled with their source schema), so a subclassed schema's records carry both its own and its parents' fields.

**File storage** mirrors the git object store: `_civex/objects/<sha256[:2]>/<sha256[2:]>`. Content-addressed and idempotent — the same file uploaded twice is stored once.

## Workflow execution and plugin tiers

**Workflow execution** is git-hook-like: definitions are YAML files in `_civex/workflows/`, checked into version control alongside your data config. The executor runs a topological sort of steps (Kahn's algorithm), resolves `step_id.output_name` input references, calls each plugin's `run()` in order, and commits once at the end.

Plugins run in one of three tiers, in increasing order of isolation:

- **Tier BUILTIN** — in-process. Ships with civex (`plugins/builtins/`); `invoke()` calls the real `WorkflowContext` directly, with no RPC boundary.
- **Tier 1 (subprocess)** — a user-authored Python file in `_civex/plugins/`, run via `uv run` as a persistent subprocess speaking the wire protocol over stdin/stdout.
- **Tier 2 (container)** — a Docker image, run fresh per operation (`docker run -i <image> <mode>`), for plugins that need a different language, system binaries, GPU access, or stricter resource limits than Tier 1 allows.

All three tiers speak the same `describe`/`run` contract, so no consumer (CLI, HTTP API, the frontend plugin panel) needs a per-tier branch. See [Writing a plugin](../extending/writing-a-plugin.md), [Container plugins](../extending/container-plugins.md), and [Wire protocol](../extending/wire-protocol.md) for the author-facing detail.
