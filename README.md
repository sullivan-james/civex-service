# civex

A command-line research data management system. Define schemas, collect records into datasets, attach files, and run data processing workflows — all locally, with an optional HTTP server and web UI.

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
- [Web UI & server](#web-ui--server)
- [Remote sync & CivexHub](#remote-sync--civexhub)
- [PostgreSQL](#postgresql)
- [Architecture](#architecture)

---

## Installation

### Recommended: pipx (installs once, works in any terminal)

```bash
# Install pipx if you don't have it
pip install pipx
pipx ensurepath        # adds civex to PATH — open a new terminal after this
```

Download the latest release and install:

```bash
gh release download --repo sullivan-james/civex-service --pattern "*.whl"
pipx install "./civex-0.0.3-py3-none-any.whl[server]"
```

Replace `0.0.3` with the version you downloaded. After installation, `civex` is available in any terminal without activating anything.

### Upgrade

```bash
pipx install --force "./civex-0.0.3-py3-none-any.whl[server]"
```

---

## Quick start

```bash
civex init                                          # initialise a project here
civex schema create trial --description "A single experimental trial"
civex schema add-field trial subject --type string --required
civex schema add-field trial duration --type float
civex dataset create study-2024
civex record add --to study-2024
civex record find --in study-2024
civex serve                                         # open http://localhost:8000
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

A dataset is a named container for records. Records within a dataset can have different schemas (e.g. a dataset can hold both `trial` and `experiment` records).

```bash
civex dataset create <name> [--description TEXT]
civex dataset list
civex dataset show <name>
civex dataset delete <name> [--yes]
```

**Example:**

```bash
civex dataset create pilot-study --description "Pilot run, n=10"
civex dataset show pilot-study
# pilot-study
#   Records  0
#   Pilot run, n=10
```

---

## Records

Records are individual data entries within a dataset. `record add` prompts for each field in the schema (including inherited fields). Required fields cannot be skipped.

```bash
civex record add    --to <dataset> [--schema SCHEMA]
civex record show   <id>
civex record update <id>
civex record find   --in <dataset> [--where field=value ...] [--limit N]
civex record delete <id> [--yes]
```

**Adding a record:**

```bash
civex record add --to pilot-study --schema trial
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

civex record add --to pilot-study --schema trial
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
civex dataset create study
civex dataset create results

# 2. Add a trigger record that holds the CSV file
civex record add --to study --schema experiment
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

## Web UI & server

```bash
civex serve [--host HOST] [--port PORT]
```

Starts a local HTTP server (default `http://127.0.0.1:8000`) with:

- A React web UI for browsing schemas, datasets, records, workflows, and jobs
- A full REST API at `/api/` (OpenAPI docs at `/docs`)
- An interactive civex shell in the browser (Terminal tab)
- Import/export YAML dumps from the Datasets page

The server requires the `[server]` extra (included in the `pipx install` command above).

---

## Remote sync & CivexHub

CivexHub is a self-hosted server that stores civex repositories centrally and lets multiple clients push and pull data. It exposes an HTTPS API and an SSH interface — SSH is the recommended transport for local development.

### Transport URLs

| Transport | URL format | When to use |
|---|---|---|
| SSH | `ssh://user@host:port/owner/repo` | Local dev, Docker; no TLS cert needed |
| HTTPS | `https://hub.example.com/owner/repo` | Production deployments behind a reverse proxy |

### Setting the remote on the client

```bash
civex remote set ssh://alice@localhost:2222/alice/myrepo

civex push    # send local commits to the hub
civex pull    # fetch hub commits into the local project
```

The remote URL is stored in `.civex/config.toml` and is read by every push/pull.

---

### CivexHub server — SSH setup

CivexHub's Docker image includes OpenSSH. SSH is configured automatically: no manual `sshd_config` editing is required.

**How it works under the hood:**

- `sshd` is started alongside the civexhub HTTP process inside the container.
- Every incoming SSH connection is forced through `civexhub-shell`, a thin command dispatcher that reads `SSH_ORIGINAL_COMMAND` and routes it to transfer-pack, receive-pack, or object fetch/put.
- Host keys are generated on first boot (`ssh-keygen -A`) and survive restarts as long as the container is not recreated.
- Authentication is public-key only — password auth is disabled. `sshd` looks up authorised keys by calling `civexhub-keys <username>`, which queries the hub's database and prints the keys in `authorized_keys` format with the forced-command prefix already applied.

**Start the hub with Docker Compose:**

```bash
cd civex-hub
docker compose up -d --build
```

This exposes:
- `8001` — HTTPS API and web UI
- `2222` — SSH (use `2222` on the host to avoid conflicting with any SSH daemon already running on the host)

---

### CivexHub server — adding SSH keys

SSH keys are managed through the hub web UI or API. There is no server-side key file to edit.

**Via the web UI:**

1. Open `http://localhost:8001` and log in.
2. Go to **Settings → SSH keys**.
3. Paste your public key (`~/.ssh/id_ed25519.pub` or similar) and give it a title.
4. Click **Add key**.

**Via the API** (useful for scripting):

```bash
# 1. Get a token
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Upload your public key
curl -s -X POST http://localhost:8001/api/v1/settings/ssh-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"my-laptop\",\"public_key\":\"$(cat ~/.ssh/id_ed25519.pub)\"}"
```

Keys can be listed and deleted via the same UI or via `GET`/`DELETE /api/v1/settings/ssh-keys`.

---

### Client — first push/pull walkthrough

```bash
# 1. Initialise a local civex project (if you haven't already)
civex init
civex schema create site --description "Camera trap site"
civex schema add-field site name --type string --required
civex dataset create sites
civex record add --to sites --schema site

# 2. Point it at a hub repository
civex remote set ssh://alice@localhost:2222/alice/camera-traps

# 3. Push
civex push
# Pushed 1 commit (3 records, 0 files)

# 4. On another machine, pull
civex pull
# Pulled 1 commit (3 records, 0 files)
```

No repository needs to be pre-created on the hub — push creates it on first contact.

---

### SSH host key verification

The first time you push to a hub over SSH, your SSH client will ask you to verify the host key:

```
The authenticity of host '[localhost]:2222 ([127.0.0.1]:2222)' can't be established.
ED25519 key fingerprint is SHA256:...
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Type `yes` to add it to `~/.ssh/known_hosts`. Subsequent pushes and pulls will connect silently. In CI or scripting contexts, add `StrictHostKeyChecking=no` in `~/.ssh/config` for the hub host.

---

## PostgreSQL

### Starting a local PostgreSQL container

```bash
docker run -d \
  --name civex-pg \
  -e POSTGRES_USER=civex \
  -e POSTGRES_PASSWORD=civex \
  -e POSTGRES_DB=civex \
  -p 5432:5432 \
  postgres:16

# Stop / remove when done
docker stop civex-pg && docker rm civex-pg
```

### Connecting civex to it

Edit `.civex/config.toml`:

```toml
[db]
url = "postgresql://civex:civex@localhost:5432/civex"
```

JSON fields (`record.data`) automatically upgrade to JSONB on PostgreSQL for indexed querying. Install the driver with `pipx inject civex psycopg2-binary`.

### Index benchmark

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

**File storage** mirrors the git object store: `.civex/objects/<sha256[:2]>/<sha256[2:]>`. Content-addressed and idempotent — the same file uploaded twice is stored once.

**Workflow execution** is git-hook-like: definitions are YAML files in `.civex/workflows/`, checked into version control alongside your data config. The executor runs a topological sort of steps, resolves `step_id.output_name` input references, and calls each plugin's `run()` in order.
