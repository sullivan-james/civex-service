# Server & UI

## Starting the server

```bash
civex serve                  # production mode — serves built UI from frontend/dist/
civex serve --reload         # development mode — auto-restarts on code changes
civex serve --host 0.0.0.0   # listen on all interfaces
civex serve --port 9000      # custom port (default: 8000)
```

The server must be run from within (or below) a directory that contains a `.civex/` project.

## Web UI

Opening [http://localhost:8000](http://localhost:8000) loads the web interface. The main sections are:

**Schemas** — Create and edit schemas, add and configure fields, view field types and restrictions.

**Datasets** — Create datasets, browse records within them, filter by schema, search, and paginate.

**Records** — Each record has a detail page showing its field values, attached files, child records (for parent schemas), workflow jobs that have run against it, and a form to edit field values.

- File fields show a file picker for upload and a download link for existing attachments.
- `datetime` fields display in your local timezone; values are stored as UTC.
- `reference` fields show a searchable dropdown of records from the target schema.
- String fields with a `choices` restriction render as a dropdown.

**Jobs** — A paginated log of all workflow job executions, filterable by status (`pending`, `running`, `completed`, `failed`). Each job shows its log output.

**Workflows** — View and edit workflow YAML files directly in the browser. Run a workflow manually by selecting it from a record's detail page.

## HTTP API

The API is available at `/api/`. All endpoints accept and return JSON.

| Resource | Base path |
|---|---|
| Schemas | `/api/schemas` |
| Datasets | `/api/datasets` |
| Records | `/api/records` |
| Files | `/api/files` |
| Workflows | `/api/workflows` |
| Jobs | `/api/jobs` |

Interactive API documentation (Swagger UI) is available at `/api/docs` while the server is running.

## Uploading files via the API

```bash
curl -X POST http://localhost:8000/api/files \
  -F "file=@/path/to/recording.wav"
# Returns: {"sha256": "...", "filename": "recording.wav", "size": 12345}
```

The returned `sha256` can then be used as the value of a `file` field when creating or updating a record.

## Running a workflow via the API

```bash
# Simple run (no file inputs)
curl -X POST http://localhost:8000/api/workflows/extract-start-time/run \
  -H "Content-Type: application/json" \
  -d '{"record_id": "abc123..."}'

# Run with file inputs (multipart)
curl -X POST http://localhost:8000/api/workflows/load-recordings/run \
  -F "record_id=abc123..." \
  -F "files=@recording1.wav" \
  -F "files=@recording2.wav"
```
