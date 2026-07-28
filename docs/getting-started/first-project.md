# Your first project

Navigate to your project directory and run:

```bash
civex init
```

This creates a `_civex/` directory with:

```
_civex/
  config.toml     # database URL and optional remote config
  civex.db        # SQLite database (if not using PostgreSQL)
  objects/        # content-addressed file storage
  workflows/      # YAML workflow definitions
  plugins/        # custom Python plugins
```

## Database provisioning

By default, `civex init` tries to set up a **Docker-managed PostgreSQL** container automatically — it only does this if a PostgreSQL driver and Docker are both available — falling back to SQLite otherwise. Force SQLite explicitly with:

```bash
civex init --sqlite
```

To connect to an existing PostgreSQL server instead of a Docker-managed one, run `civex db setup-postgres` after `civex init` (auto-detects a local server and prompts interactively, or pass `--url` to skip prompts):

```bash
civex db setup-postgres --url postgresql+psycopg2://user:pass@host:5432/dbname
```

See [PostgreSQL](../guides/postgresql.md) for the full setup story, including why every project needs its own database.

## Next step

[Take the five-minute tour →](tour.md)
