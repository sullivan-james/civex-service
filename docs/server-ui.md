# Server & UI

## Starting the server

The desktop app starts the server automatically. If you're using the CLI:

```bash
civex serve                  # production mode — serves built UI from frontend/dist/
civex serve --reload         # development mode — auto-restarts on code changes
civex serve --host 0.0.0.0   # listen on all interfaces
civex serve --port 9000      # custom port (default: 8000)
```

The server must be run from within (or below) a directory that contains a `_civex/` project.

## Web UI

Opening [http://localhost:8000](http://localhost:8000) (or wherever you configured it) loads the web interface. The main sections are:

**Schemas** — Create and edit schemas, add and configure fields, view field types and restrictions.

**Collections** — Create collections, browse records within them, filter by schema, search, and paginate.

**Records** — Each record has a detail page showing its field values, attached files, child records (for parent schemas), workflow jobs that have run against it, and a form to edit field values.

- File fields show a file picker for upload and a download link for existing attachments.
- `datetime` fields display in your local timezone; values are stored as UTC.
- `reference` fields show a searchable dropdown of records from the target schema.
- String fields with a `choices` restriction render as a dropdown.
- A **"⊙ from filename"** button appears on text/number/date/datetime fields whenever a file field on the same record has a file attached — lets you extract a value from the filename using a regex, without writing a workflow.

**Runs** — A paginated log of all workflow job executions, filterable by status (`pending`, `running`, `completed`, `failed`). Each job shows its log output.

**Workflows** — View and edit workflow YAML files directly in the browser. Run a workflow manually by selecting it from a record's detail page.

## HTTP API

All endpoints are under `/api/`. Responses are JSON. Interactive documentation (Swagger UI) is available at `/api/docs` while the server is running.

### Schemas

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/schemas` | List all schemas |
| `POST` | `/api/schemas` | Create a schema |
| `GET` | `/api/schemas/{name}` | Get a schema with its fields |
| `PATCH` | `/api/schemas/{name}` | Update schema name or description |
| `DELETE` | `/api/schemas/{name}` | Delete a schema |
| `POST` | `/api/schemas/{name}/fields` | Add a field |
| `PATCH` | `/api/schemas/{name}/fields/{field}` | Update a field (rename, restrictions) |
| `DELETE` | `/api/schemas/{name}/fields/{field}` | Remove a field |

### Datasets

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/datasets` | List all datasets |
| `POST` | `/api/datasets` | Create a dataset |
| `GET` | `/api/datasets/{name}` | Get a dataset |
| `PATCH` | `/api/datasets/{name}` | Update name or description |
| `DELETE` | `/api/datasets/{name}` | Delete a dataset and all its records |

### Records

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/records` | List records (supports `dataset`, `schema`, `parent_record_id`, `search`, `limit`, `offset`) |
| `POST` | `/api/records` | Create a record |
| `GET` | `/api/records/count` | Count records matching filters |
| `GET` | `/api/records/{id}` | Get a single record |
| `PATCH` | `/api/records/{id}` | Update a record's data |
| `DELETE` | `/api/records/{id}` | Delete a record |

### Files

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/files` | Upload a file (multipart). Returns `{sha256, filename, size}`. |
| `GET` | `/api/files/{sha256}` | Download a file by hash |

```bash
curl -X POST http://localhost:8000/api/files \
  -F "file=@/path/to/recording.wav"
# → {"sha256": "abc123…", "filename": "recording.wav", "size": 4096000}
```

The returned `sha256` can then be used as the value of a `file` field when creating or updating a record.

### Workflows

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/workflows` | List all workflow definitions |
| `GET` | `/api/workflows/{stem}` | Get a workflow (including YAML source) |
| `PUT` | `/api/workflows/{stem}` | Create or update a workflow YAML |
| `DELETE` | `/api/workflows/{stem}` | Delete a workflow |
| `POST` | `/api/workflows/{name}/run` | Run a workflow |

```bash
# Simple run (no file inputs)
curl -X POST http://localhost:8000/api/workflows/extract-start-time/run \
  -H "Content-Type: application/json" \
  -d '{"record_id": "abc123…"}'

# Run with file inputs (multipart)
curl -X POST http://localhost:8000/api/workflows/load-recordings/run \
  -F "record_id=abc123…" \
  -F "files=@recording1.wav" \
  -F "files=@recording2.wav"
```

### Jobs

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/jobs` | List jobs (supports `status`, `record_id`, `offset`, `limit`) |
| `GET` | `/api/jobs/count` | Count jobs matching filters |
| `GET` | `/api/jobs/{id}` | Get a single job |
| `POST` | `/api/jobs/drain` | Process all pending jobs immediately |
