# Back up a project

**Goal:** a copy you can restore everything from: records, history, settings and
files.

## What makes up a project

```text
my-project/
  _civex/
    config.toml     volumes, homes, retention, sync and other settings
    civex.db        the database (SQLite projects only)
    objects/        files on the default volume
    workflows/      workflow YAML
    plugins/        custom plugins
    exports/        export folders (can be rebuilt; skip them if you like)
/media/archive/civex/   any volume outside the project, one folder per volume
```

On PostgreSQL the database lives on the server instead of in `civex.db`.

## A full backup (SQLite)

1. Stop `civex serve` (and the desktop app) for this project, so the database
   isn't written halfway through the copy.
2. Copy the `_civex/` folder.
3. Copy each volume folder that is outside the project. `civex store list` shows
   their paths.

```bash
civex store list
rsync -a my-project/_civex/            /backup/my-project/_civex/
rsync -a /media/archive/civex/         /backup/volumes/archive/
```

Stored files never change once written (they're named by their content hash),
so after the first copy, `rsync` only copies new files.

**Restoring:** copy the folders back. If a volume ends up at a different path,
point civex at it with `civex store update archive --path /new/path`. The
volume's `.civex-volume` marker comes with it, so civex knows it's the same
drive.

## PostgreSQL

Back up the database with PostgreSQL's own tools, plus the folders above (minus
`civex.db`):

```bash
civex db status                         # shows the connection URL
pg_dump --format=custom --file civex.pgdump "postgresql://…"
```

## A portable copy: `civex dump`

`civex dump` writes schemas, collections, records, workflows and plugins to one
YAML file that any civex can read, whatever its database:

```bash
civex dump --output backup.yaml
civex dump --no-data --output structure.yaml   # schemas and workflows only

# into a new, empty project
civex init other-project && cd other-project
civex restore backup.yaml
```

It is **not** a full backup. It leaves out:

- stored files (copy the volumes),
- change history and Activity,
- saved views and saved exports,
- settings in `config.toml`.

## Projects that sync

The authority holds the shared copy, so back up the authority as above. A device
can be cloned again from it at any time. A device's identity (its key) is in
`~/.civex/sync.toml`, outside the project, and a copied project folder doesn't
carry it: a restored device joins again with a new invite.

## Moving to another database

To switch between SQLite and PostgreSQL, don't dump and restore. Use
`civex db move`, which copies and checks everything, history included, before
switching. See [PostgreSQL](../guides/postgresql.md).
