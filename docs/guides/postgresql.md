# PostgreSQL

By default a civex project uses SQLite. Switching to PostgreSQL gives you indexed querying over record data (JSON columns automatically upgrade to `JSONB` via SQLAlchemy's `with_variant`) and is a better fit once a project's data or concurrent access grows. All setup and status commands live under the [`civex db` command group](../cli-reference.md#civex-db).

## Automatic setup (recommended)

`civex init` uses Docker PostgreSQL by default (pass `--sqlite` to opt out). It starts a container named after your project (`civex-<project-name>`) on its own auto-picked port with its own named volume, and writes the resulting URL to `_civex/config.toml` for you — nothing to edit by hand.

Already on SQLite and want to switch a project over later:

=== "CLI"
    ```bash
    civex db setup-docker
    ```

=== "Web UI"
    Go to **Settings → Database → Docker-managed PostgreSQL** and click **Start / recreate container**.

**Each civex project needs its own database — civex has no multi-tenant isolation.** There's no per-project namespacing in the schema (schema and collection names are globally unique within a database), so two projects pointed at the same Postgres database will collide or silently mix data. `civex db setup-docker` avoids this automatically by giving every project its own container; if you manage Postgres yourself instead (below), give every project its own database, and preferably its own container.

## Manual setup

```bash
docker run -d \
  --name civex-pg-myproject \
  -e POSTGRES_USER=civex \
  -e POSTGRES_PASSWORD=civex \
  -e POSTGRES_DB=civex_myproject \
  -p 5432:5432 \
  postgres:16

# Stop / remove when done
docker stop civex-pg-myproject && docker rm civex-pg-myproject
```

Point civex at the server:

=== "CLI"
    ```bash
    civex db setup-postgres --url postgresql+psycopg2://civex:civex@localhost:5432/civex_myproject
    ```

    Or edit `_civex/config.toml` directly:

    ```toml
    [db]
    url = "postgresql://civex:civex@localhost:5432/civex_myproject"
    ```

=== "Web UI"
    Go to **Settings → Database**, click **Change URL…**, and paste the connection string. Civex tests the connection and migrates it before switching over — the target database itself is left untouched.

JSON fields (`record.data`) automatically upgrade to `JSONB` on PostgreSQL for indexed querying. Install the driver with `pipx inject civex psycopg2-binary`.

## Checking status and migrations

=== "CLI"
    ```bash
    civex db status   # connection, migration, and Docker container status
    civex db current  # current migration revision
    civex db migrate  # apply pending migrations now
    ```

=== "Web UI"
    **Settings → Database** shows the connection URL, dialect, and a badge (`up to date`, `pending migrations`, or `unreachable`). A **Run migrations** button appears whenever migrations are pending.

## Index benchmark

A benchmark script is included that shows the query speedup from the composite B-tree and GIN indexes added to the `records` table. It seeds 100 000 records, measures query times before and after creating the indexes, and prints a comparison table with `EXPLAIN ANALYZE` output.

```bash
docker run -d \
  --name civex-bench \
  -e POSTGRES_USER=civex \
  -e POSTGRES_PASSWORD=civex \
  -e POSTGRES_DB=civex_bench \
  -p 5432:5432 \
  postgres:16

PG_URL=postgresql://civex:civex@localhost/civex_bench \
  python tests/bench_indexes.py

docker stop civex-bench && docker rm civex-bench
```
