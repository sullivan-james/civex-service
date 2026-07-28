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

**Layer rules:**

- `cli` → `services` (via `AppContext`). Never talks to repos or DB directly.
- `plugins` → `WorkflowContext` only. Never imports SQLAlchemy or sessions.
- `services` → `repositories/protocols` (interfaces, not implementations). Never imports from `cli`.
- `repositories/local` → `db/models`. The only layer that touches SQLAlchemy models.
- `domain` has no imports from the rest of civex — it is always safe to import anywhere.

**File storage** mirrors the git object store: `_civex/objects/<sha256[:2]>/<sha256[2:]>`. Content-addressed and idempotent — the same file uploaded twice is stored once.

**Workflow execution** is git-hook-like: definitions are YAML files in `_civex/workflows/`, checked into version control alongside your data config. The executor runs a topological sort of steps, resolves `step_id.output_name` input references, and calls each plugin's `run()` in order.
