# CLI reference

Run `civex --help` or `civex <command> --help` for up-to-date flag descriptions. This page summarises the commands and their most useful options.

## `civex init`

Initialise a new civex project.

```bash
civex init [PATH] [--sqlite] [--bare]
```

| Flag | Description |
|---|---|
| `--sqlite` | Force SQLite instead of trying Docker-managed PostgreSQL first |
| `--bare` | Create a bare repository (remote storage only, no working directory) |

By default, `civex init` tries to provision a Docker-managed PostgreSQL container automatically, falling back to SQLite if a PostgreSQL driver or Docker isn't available. See [Your first project](getting-started/first-project.md) for the full provisioning story, including connecting to an existing PostgreSQL server via `civex db setup-postgres`.

---

## `civex serve`

Start the HTTP server and web UI.

```bash
civex serve [--host HOST] [--port PORT] [--reload] [--allow-remote] [--log-level LEVEL]
```

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Interface to listen on. Binding to any non-loopback address (e.g. `0.0.0.0`) exits with an error unless `--allow-remote` is also passed. |
| `--port` | `8000` | TCP port |
| `--reload` | off | Auto-restart on source changes (development) |
| `--allow-remote` | off | Permit binding to a non-loopback address. Required whenever `--host` isn't a loopback address, because the server has no authentication — only pass this on a trusted network behind a reverse proxy or firewall. |
| `--log-level` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. Overrides `[logging]` in `config.toml`. |

API docs are served at `/docs` (not under `/api/`).

---

## `civex schema`

| Command | Description |
|---|---|
| `civex schema create <name> [-d TEXT] [--parent SCHEMA]` | Define a new schema, optionally inheriting from a parent |
| `civex schema list` | List all schemas |
| `civex schema show <name>` | Inspect a schema's fields (including inherited) |
| `civex schema update <name> [--rename NAME] [-d TEXT] [--display-field FIELD ...] [--clear-display-fields]` | Update name, description, or the ordered fields joined to form a record's natural name (`--display-field` is repeatable) |
| `civex schema add-field <schema> <field> --type TYPE [--required] [restrictions]` | Add a field |
| `civex schema update-field <schema> <field> [...]` | Update a field's name, required flag, or restrictions |
| `civex schema remove-field <schema> <field>` | Remove a field (stored data is not deleted) |
| `civex schema delete <name>` | Delete a schema and its fields (does not delete records) |

**Field types:** `string`, `integer`, `float`, `boolean`, `date`, `datetime`, `file`, `file_list`, `reference`

**Restriction flags** (on `add-field` and `update-field`):

| Flag | Applies to | Description |
|---|---|---|
| `--required` / `--optional` | all | Whether the field must be set |
| `--min VALUE` / `--max VALUE` | `integer`, `float` | Value range |
| `--min VALUE` / `--max VALUE` | `date`, `datetime` | Date range (ISO string) |
| `--choices A,B,C` | `string` | Comma-separated allowed values |
| `--max-length N` | `string` | Maximum character length |
| `--accept .ext,.ext` | `file`, `file_list` | Comma-separated allowed extensions |
| `--max-size BYTES` | `file`, `file_list` | Maximum file size in bytes |
| `--references SCHEMA` | `reference` | Target schema name |
| `--clear-restrictions` | all | Remove all restrictions (on `update-field`) |

---

## `civex collection`

Collections are named containers for records — see [Collections & records](guides/collections-and-records.md).

| Command | Description |
|---|---|
| `civex collection create <name> [-d TEXT]` | Create a new collection |
| `civex collection list` | List all collections |
| `civex collection show <name>` | Summary with record counts per schema |
| `civex collection graph <name>` | Show the schema hierarchy present in a collection |
| `civex collection update <name> [--rename NAME] [-d TEXT]` | Rename or update the description |
| `civex collection delete <name> [--yes]` | Delete a collection and all its records |

---

## `civex record`

| Command | Description |
|---|---|
| `civex record add --to COLLECTION --schema SCHEMA` | Add a record, prompting for each field |
| `civex record show <record-id>` | Show a record's field values |
| `civex record update <record-id>` | Update a record, prompting for each field with the current value as default |
| `civex record find --in COLLECTION [--schema SCHEMA] [--where FIELD=VALUE]... [--limit N]` | List records |
| `civex record delete <record-id> [--yes]` | Delete a record |
| `civex record delete-all <collection> [--schema SCHEMA] [--yes]` | Delete all records in a collection (optionally filtered by schema) |

`--where` is repeatable — all conditions must match. `<record-id>` accepts a full UUID or any unique prefix.

```bash
civex record find --in study-2024 --schema trial --where "outcome=pass" --where "location=Brazil" --limit 20
```

---

## `civex workflow`

| Command | Description |
|---|---|
| `civex workflow list` | List all workflow definitions in `_civex/workflows/` |
| `civex workflow run <name> --record RECORD_ID [--input name=value]...` | Run a workflow manually |

For `files`-typed inputs, `value` is a glob pattern:
```bash
civex workflow run load-recordings --record abc123 --input files=data/*.wav
```

---

## `civex automation`

Processes and inspects workflow jobs — the queue that both automatic triggers and `civex workflow run` enqueue into. See [Automation](guides/automation.md) for the day-to-day workflow.

| Command | Description |
|---|---|
| `civex automation run [--watch] [--interval N]` | Process all pending jobs now; `--watch` keeps polling (default interval 5s) |
| `civex automation jobs [--status STATUS]` | List jobs (`pending`, `running`, `completed`, `failed`) |
| `civex automation logs <job-id>` | Show captured log output for a job |
| `civex automation enqueue --workflow NAME --record RECORD_ID` | Manually enqueue a job without running it immediately |
| `civex automation stats` | Show failed step-execution counts by plugin, across all jobs |

---

## `civex status`

```bash
civex status
```

Shows staged (uncommitted) changes and commits not yet pushed to the configured remote.

---

## `civex dump` / `civex restore`

```bash
civex dump [-o FILE] [--no-data] [--no-workflows]
civex restore <dump-file> [--yes]
```

| Flag | Description |
|---|---|
| `-o`, `--output FILE` | Output path (default: `civex-dump.yaml`) |
| `--no-data` | Omit records from the export |
| `--no-workflows` | Omit workflows and plugins from the export |
| `--yes` (restore) | Skip the confirmation prompt |

File attachments are not included — see [Files](guides/files.md#backing-up-files).

---

## `civex remote` / `civex push` / `civex pull` / `civex clone`

```bash
civex remote set <url> [--remote-civex PATH]
civex remote show
civex remote unset

civex push
civex pull

civex clone <url> [local_dir] [--remote-civex PATH]
```

See [Remote sync](guides/remote-sync.md) for the full workflow.

---

## `civex db`

| Command | Description |
|---|---|
| `civex db setup-docker` | Set up a Docker-managed PostgreSQL container for this project |
| `civex db setup-postgres [--url URL]` | Configure civex to use an existing PostgreSQL server |
| `civex db teardown` | Stop and remove this project's Docker-managed container and its data |
| `civex db status` | Show connection, migration, and (if applicable) Docker container status |
| `civex db current` | Show the current migration revision |
| `civex db migrate` | Apply pending migrations now |

---

## `civex store`

Manage file storage volumes (for splitting object storage across multiple disks/mounts).

```bash
civex store list
civex store add <name> <path> [--allocated-gb N]
civex store update <name> [--path PATH] [--allocated-gb N]
civex store remove <name>
civex store queue <name>...
```

---

## `civex ai`

Configure the built-in AI assistant.

```bash
civex ai status
civex ai set-key
civex ai set-model
civex ai usage
civex ai clear
```

---

## `civex policy`

```bash
civex policy list    # list org-authored policy documents (_civex/policies/*.md)
civex policy show <name>
```

---

## `civex auth`

Authenticate with a civex-hub server.

```bash
civex auth login
civex auth logout
civex auth status
```

---

## Other commands

| Command | Description |
|---|---|
| `civex resolve <id>` | Identify a resource (schema, collection, or record) by UUID or prefix |
| `civex demo [PATH]` | Create a demo project pre-populated with example schemas and records (default: `./civex-demo`) |
| `civex shell` | Start an interactive civex shell — run commands without the `civex` prefix |
| `civex license` | Print civex's software license |
| `civex plugin list` | List registered plugins (built-ins and custom) |
| `civex plugin info <plugin-id>` | Show a plugin's inputs, outputs, capabilities, and config schema |
