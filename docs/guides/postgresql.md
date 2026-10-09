# PostgreSQL

A project uses SQLite unless you choose otherwise. PostgreSQL suits bigger
projects and many people working at once: record data is stored as `JSONB` with
indexes. The driver is included with civex.

## New project

`civex init` starts a PostgreSQL container for the project when Docker is
available, and uses SQLite otherwise:

```bash
civex init            # Docker PostgreSQL if possible
civex init --sqlite   # always SQLite
```

The container is named `civex-<project>`, with its own port and volume, and its
URL is written to `_civex/config.toml`.

## Existing project: move it

`civex db move` copies everything (records, history, runs), checks the copy, and
only then switches over:

```bash
civex db move --to docker
civex db move --to postgres --host db.example.org --database civex --user ada
civex db move --to sqlite
civex db moves            # past moves
civex db revert <id>      # switch back
```

- The original database is never changed, so stopping halfway leaves the project
  as it was.
- Row counts of every table and a sample of records are compared before
  switching.
- The destination must be empty.
- `revert` switches back. Anything added since stays in the new database.

**In the app:** **Settings → Database → Move to another database…**. Past moves
and **Switch back** are on its **Move history** tab.

Files aren't in the database, so a move doesn't touch them.

!!! warning "One database per project"
    Schema and collection names are unique per database, and civex has no other
    separation between projects. Two projects pointed at one database will mix.
    `civex db setup-docker` gives each project its own container. If you run
    PostgreSQL yourself, give each project its own database.

## Your own server

```bash
civex db setup-postgres                               # finds a local server, asks the rest
civex db setup-postgres --url postgresql+psycopg2://civex:secret@db:5432/civex_myproject
```

This points the project at an **empty** database and builds it. It doesn't copy
data: for that, use `db move`. In the app: **Settings → Database → Advanced** →
connection URL → **Test and switch**.

`civex db setup-docker` likewise starts a new empty container, and refuses if the
current database has records.

## Status and upgrades

```bash
civex db status     # connection, migration state, Docker container
civex db migrate    # update the database structure now
```

New civex versions update the database structure the next time a project opens.
**Settings → Database** shows the connection and offers **Update it** when an
update is waiting.
