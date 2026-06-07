# civex

A command-line research data management system. Define schemas, collect records into datasets, attach files, and run data processing workflows — all locally, with a server/collaborative layer designed to follow.

---

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Project initialisation](#project-initialisation)
- [Schemas](#schemas)
- [Datasets](#datasets)
- [Records](#records)
- [Workflows](#workflows)
- [Plugins](#plugins)
- [PostgreSQL](#postgresql)
- [Architecture](#architecture)

---

## Installation

```bash
python -m venv venv
source venv/bin/activate

pip install -e .                   # SQLite (default)
pip install -e ".[postgres]"       # add PostgreSQL driver
pip install -e ".[workflows]"      # add pandas for CSV workflow plugins
pip install -e ".[postgres,workflows]"  # both
```

The `civex` command is available anywhere within the activated environment.

---

## Quick start

```bash
civex init                                          # initialise a project here
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

Creates a `.civex/` directory at `PATH` (default: current directory):

```
.civex/
  config.toml     # database URL and optional remote config
  civex.db        # SQLite database (default)
  objects/        # content-addressed file storage (git-style)
  workflows/      # YAML workflow definitions
  plugins/        # user-written custom plugins
```

All other commands walk up from the current directory to find `.civex/`, the same way `git` finds `.git/`.

---

## Schemas

A schema defines the structure of records — fields, types, and whether they are required. Schemas can inherit fields from a parent schema.

```bash
civex schema create <name> [--description TEXT] [--parent SCHEMA]
civex schema list
civex schema show <name>
civex schema add-field <schema> <field> --type TYPE [--required]
civex schema delete <name>
```

**Field types:** `integer` `float` `string` `boolean` `file`

**Example — inheritance:**

```bash
civex schema create experiment --description "Common fields"
civex schema add-field experiment subject --type string --required
civex schema add-field experiment date   --type string

civex schema create trial --parent experiment --description "A single trial"
civex schema add-field trial duration  --type float
civex schema add-field trial condition --type string

civex schema show trial
# Field     Type    Required  Source
# duration  float             trial
# condition string            trial
# subject   string  yes       ↑ experiment
# date      string            ↑ experiment
```

Own fields shadow parent fields of the same name. Inheritance is resolved recursively, so chains of any depth work.

---

## Datasets

A dataset is a named collection of records that all conform to one schema.

```bash
civex dataset create <name> --schema <schema> [--description TEXT]
civex dataset list
civex dataset show <name>
civex dataset delete <name> [--yes]
```

**Example:**

```bash
civex dataset create pilot-study --schema trial --description "Pilot run, n=10"
civex dataset show pilot-study
# pilot-study
#   Schema   trial
#   Records  0
#   Pilot run, n=10
```

---

## Records

Records are individual data entries within a dataset. `record add` prompts for each field in the schema (including inherited fields). Required fields cannot be skipped.

```bash
civex record add    --to <dataset>
civex record show   <id>
civex record update <id>
civex record find   --in <dataset> [--where field=value ...] [--limit N]
civex record delete <id> [--yes]
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

Multiple `--where` conditions are AND'd. Filtering runs in Python against the JSON record data.

**Short IDs:** commands accept a short prefix of the record UUID, like `git`:

```bash
civex record show   0c45e37f
civex record update 0c45e37f
civex record delete 0c45e37f --yes
```

**File fields:** for fields of type `file`, provide a local file path when prompted. The file is read, hashed (SHA-256), and stored content-addressed in `.civex/objects/`. Identical files are stored once.

```bash
civex schema add-field trial raw_data --type file

civex record add --to pilot-study
#   duration (float) []: 30.0
#   condition (string) []: B
#   raw_data (file) []: /path/to/eeg_session_01.csv
#   subject (string) [required]: S04
```

The record stores a reference `{sha256, filename, size}` — the bytes live in `.civex/objects/<sha256[:2]>/<sha256[2:]>`.

---

## Workflows

A workflow is a YAML file in `.civex/workflows/` that defines a pipeline of plugin steps. Workflows are version-controllable, portable, and local-first — they run on your machine against your data.

```bash
civex workflow list
civex workflow run <name> --record <id>
```

### YAML format

```yaml
name: import-csv-records
description: Create one record per row from a CSV file field

steps:
  - id: load
    plugin: civex.load_file
    config:
      field: raw_data          # field name on the trigger record

  - id: parse
    plugin: civex.load_csv
    inputs:
      bytes: load.bytes        # step_id.output_name
    config:
      delimiter: ","

  - id: create
    plugin: civex.rows_to_records
    inputs:
      table: parse.table
    config:
      dataset: processed-trials
      field_mapping:           # csv_column → schema_field
        subject_id: subject
        duration_ms: duration
```

Each step's `inputs` references the output of an earlier step using `step_id.output_name` notation. The executor resolves these in topological order, so steps can appear in any order in the file as long as the dependency graph is acyclic.

### End-to-end example

```bash
# 1. Prepare schemas and datasets
civex schema create experiment
civex schema add-field experiment subject  --type string --required
civex schema add-field experiment raw_data --type file
civex dataset create study   --schema experiment
civex dataset create results --schema experiment

# 2. Add a trigger record that holds the CSV file
civex record add --to study
#   subject (string) [required]: batch-01
#   raw_data (file) []: /path/to/data.csv

# 3. Create the workflow
cat > .civex/workflows/import-rows.yaml << 'EOF'
name: import-rows
description: Create one record per CSV row
steps:
  - id: load
    plugin: civex.load_file
    config:
      field: raw_data
  - id: parse
    plugin: civex.load_csv
    inputs:
      bytes: load.bytes
  - id: create
    plugin: civex.rows_to_records
    inputs:
      table: parse.table
    config:
      dataset: results
      field_mapping:
        subject: subject
EOF

# 4. Run
civex workflow run import-rows --record <id>
civex record find --in results
```

---

## Plugins

Plugins are the individual steps within a workflow. Each plugin takes named inputs, a typed config, and a workflow context, and returns named outputs.

### Built-in plugins

| ID | Category | Inputs | Config | Outputs |
|---|---|---|---|---|
| `civex.load_file` | data-sources | — | `field: str` | `bytes`, `filename`, `sha256` |
| `civex.load_csv` | data-sources | `bytes` | `delimiter`, `encoding` | `table` (DataFrame) |
| `civex.get_field` | data-access | — | `field: str` | `value` |
| `civex.save_field` | outputs | `value` | `field: str` | — |
| `civex.rows_to_records` | outputs | `table` | `dataset`, `field_mapping` | `created` (int) |

`civex.load_csv` and `civex.rows_to_records` require the `[workflows]` extra (`pandas`).

### Writing a custom plugin

Create a Python file in `.civex/plugins/`. It must define a class named `Plugin` that subclasses `BasePlugin`:

```python
# .civex/plugins/normalise.py
from typing import Any
from pydantic import BaseModel
from civex.plugins.base import BasePlugin, WorkflowContext


class Plugin(BasePlugin):
    id = "my.normalise"
    name = "Normalise Values"
    category = "transformations"

    class Config(BaseModel):
        column: str
        factor: float = 1.0

    def run(
        self,
        inputs: dict[str, Any],
        config: Config,
        ctx: WorkflowContext,
    ) -> dict[str, Any]:
        df = inputs["table"].copy()
        df[config.column] = df[config.column] * config.factor
        return {"table": df}
```

Use it in a workflow:

```yaml
steps:
  - id: normalise
    plugin: my.normalise
    inputs:
      table: parse.table
    config:
      column: duration
      factor: 0.001
```

Custom plugins are discovered automatically from `.civex/plugins/*.py` when `civex workflow run` executes. They are never sent to a server.

### WorkflowContext

The `ctx` argument gives plugins access to the trigger record and the data layer:

```python
ctx.record              # RecordDTO — the record that triggered the workflow
ctx.dataset             # DatasetDTO — the dataset it belongs to
ctx.get_file(sha256)    # bytes — retrieve a stored file by hash
ctx.update_record(data) # write field values back to the trigger record
ctx.create_record(dataset_name, data)  # create a new record in any dataset
```

---

## PostgreSQL

Edit `.civex/config.toml` to point at a PostgreSQL database:

```toml
[db]
url = "postgresql://user:password@localhost:5432/civex"
```

JSON fields (`record.data`, `field.restrictions`) automatically upgrade to JSONB on PostgreSQL for indexed querying. Install the driver with `pip install -e ".[postgres]"`.

---

## Architecture

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
    config.py      # Project root discovery + config loading
    context.py     # AppContext factory (wires all repos + services)
```

**Layer rules:**
- `cli` → `services` (via `AppContext`). Never talks to repos or DB directly.
- `plugins` → `WorkflowContext` only. Never imports SQLAlchemy or sessions.
- `services` → `repositories/protocols` (interfaces, not implementations). Never imports from `cli`.
- `repositories/local` → `db/models`. The only layer that touches SQLAlchemy models.
- `domain` has no imports from the rest of civex — it is always safe to import anywhere.

**File storage** mirrors the git object store: `.civex/objects/<sha256[:2]>/<sha256[2:]>`. Content-addressed and idempotent — the same file uploaded twice is stored once.

**Workflow execution** is git-hook-like: definitions are YAML files in `.civex/workflows/`, checked into version control alongside your data config. The executor runs a topological sort of steps, resolves `step_id.output_name` input references, and calls each plugin's `run()` in order.

### Future layers

```toml
# .civex/config.toml — optional remote block (absent = local-only)
[remote]
url   = "https://civex.example.com"
token = "pat_abc123"
```

A future FastAPI server will expose the same `AppContext` via HTTP. The service layer is already server-ready — the CLI and server will share identical business logic. On the server, only registered built-in plugins execute; raw code and `.civex/plugins/` are local-only.
