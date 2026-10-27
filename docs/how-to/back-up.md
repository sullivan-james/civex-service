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

## A portable copy: `civex bundle`

`civex bundle export` writes schemas, collections, records, the stored files
the records cite, and the project's workflows and plugins to one file that
any civex can read, whatever its database. Records keep their ids, so a record
inside another, and one that references another, still line up in the project
the bundle is read into. In the app it is **Export bundle…** and **Import
bundle…** on the Collections page.

```bash
civex bundle export --output backup.civex.zip
civex bundle export --no-files --output light.civex.zip   # records cite the files, bytes left out
civex bundle export --no-data --output structure.civex.zip # schemas and workflows only
civex bundle export --collection survey-2024               # one collection (repeatable)
civex bundle show backup.civex.zip                         # what a bundle holds

# into another project
civex init other-project && cd other-project
civex bundle import backup.civex.zip
```

Importing matches schemas and collections by name (one already there is
reused, and a schema gains only the fields it lacks) and records by id (one
already there, live or deleted, is left as it is), so a bundle can be imported
again after more records were added. The import is one event in Activity.
A bundle's plugins are code: read what lands in `_civex/plugins/` before
running workflows.

A bundle is **not** a full backup. It leaves out:

- change history and Activity,
- saved views and saved exports,
- settings in `config.toml`,
- files on a drive that can't be reached when it is written (the records
  still cite them; `civex bundle show` lists how many were left out).

A YAML dump written by `civex dump` in an older release is read by that
release's `civex restore`; export a bundle from there.

## Projects that sync

The authority holds the shared copy, so back up the authority as above. A device
can be cloned again from it at any time. A device's identity (its key) is in
`~/.civex/sync.toml`, outside the project, and a copied project folder doesn't
carry it: a restored device joins again with a new invite.

## Moving to another database

To switch between SQLite and PostgreSQL, don't dump and restore. Use
`civex db move`, which copies and checks everything, history included, before
switching. See [PostgreSQL](../guides/postgresql.md).
