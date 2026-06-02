# civex-service

A command-line tool for managing flexible research data. Define schemas, organise records into datasets, and attach files — all locally, with a server/collaborative layer designed to follow.

---

## Installation

```bash
python -m venv venv
source venv/bin/activate

pip install -e .                  # local SQLite (default)
pip install -e ".[postgres]"      # add PostgreSQL driver
```

The `civex` command is then available anywhere within the activated environment.

---

## Quick start

```bash
civex init                        # initialise a project in the current directory
civex schema create trial --description "A single experimental trial"
civex schema add-field trial subject --type string --required
civex schema add-field trial duration --type float
civex dataset create study-2024 --schema trial
civex record add --to study-2024
civex record find --in study-2024
```

---

## Project initialisation

```
civex init [PATH]
```

Creates a `.civex/` directory at `PATH` (default: current directory), containing:

```
.civex/
  config.toml     # database URL and optional remote config
  civex.db        # SQLite database (local default)
  objects/        # content-addressed file storage
```

All other commands walk up from the current directory to find `.civex/`, the same way git finds `.git/`.

To point at a PostgreSQL database instead of SQLite, edit `.civex/config.toml`:

```toml
[db]
url = "postgresql://user:password@localhost:5432/civex"
```

---

## Schemas

A schema defines the structure of your data — its fields, types, and constraints. Schemas can inherit fields from a parent schema.

```bash
civex schema create <name> [--description TEXT] [--parent SCHEMA]
civex schema list
civex schema show <name>
civex schema add-field <schema> <field> --type TYPE [--required]
civex schema delete <name>
```

**Available types:** `integer`, `float`, `string`, `boolean`, `file`

**Example — schema inheritance:**

```bash
civex schema create experiment --description "Common fields for all experiments"
civex schema add-field experiment subject --type string --required
civex schema add-field experiment date --type string

civex schema create trial --parent experiment --description "A single trial"
civex schema add-field trial duration --type float
civex schema add-field trial condition --type string

civex schema show trial
# Field     Type    Required  Source
# duration  float             trial
# condition string            trial
# subject   string  yes       ↑ experiment
# date      string            ↑ experiment
```

---

## Datasets

A dataset is a named collection of records that all conform to one schema.

```bash
civex dataset create <name> --schema <schema> [--description TEXT]
civex dataset list
civex dataset show <name>
civex dataset delete <name>
```

**Example:**

```bash
civex dataset create pilot-study --schema trial --description "Pilot run, n=10"
civex dataset show pilot-study
```

---

## Records

Records are individual data entries within a dataset. `record add` prompts for each field defined on the schema (including inherited fields). Required fields cannot be skipped.

```bash
civex record add --to <dataset>
civex record show <id>
civex record update <id>
civex record find --in <dataset> [--where field=value ...] [--limit N]
civex record delete <id>
```

**Adding a record:**

```bash
civex record add --to pilot-study
#   duration (float) []: 45.3
#   condition (string) []: A
#   subject (string) [required]: S01
#   date (string) []: 2024-03-15
# Added record 0c45e37f-...
```

**Filtering:**

```bash
civex record find --in pilot-study --where condition=A
civex record find --in pilot-study --where condition=A --where subject=S01
civex record find --in pilot-study --limit 10
```

**Short IDs:** Most commands accept the first 8 characters of a record UUID, similar to git short hashes:

```bash
civex record show 0c45e37f
civex record delete 0c45e37f --yes
```

**File fields:** For fields of type `file`, provide a path when prompted. The file is stored content-addressed in `.civex/objects/` and deduplicated automatically.

```bash
civex schema add-field trial raw_data --type file

civex record add --to pilot-study
#   duration (float) []: 30.0
#   condition (string) []: B
#   raw_data (file) []: /path/to/eeg_session_01.csv
#   subject (string) [required]: S04
```

The stored value is a reference (`filename`, `sha256`, `size`) — the bytes live in `.civex/objects/`.

---

## Workflows and plugins

Workflow and plugin commands are reserved for the data processing pipeline layer, which is not yet implemented.

```bash
civex workflow list
civex plugin list
```

---

## Remote (coming)

A future `[remote]` block in `config.toml` will enable push/pull sync with a hosted civex server:

```toml
[remote]
url = "https://civex.example.com"
token = "pat_abc123"
```

The local `.civex/` directory is designed to work like a git repository — fully functional offline, with sync to a remote as an optional layer on top.
