# civex-hub

Self-hosted repository hosting for [civex](../README.md). Stores repositories in PostgreSQL (one schema per repo), serves a React frontend, and speaks the same push/pull protocol as the civex CLI.

## Features

- **Repository hosting** — create public or private repositories, push and pull with `civex push` / `civex pull` / `civex clone`
- **Organizations and teams** — group users into orgs, create teams within orgs, grant fine-grained read/write/admin access to repos
- **Token authentication** — password login issues bearer tokens; the civex CLI stores them via `civex auth login`
- **File object store** — binary file fields are stored separately (filesystem or S3) and transferred on demand
- **Web UI** — React frontend served at the root; API docs at `/docs`

## Quick start (Docker)

```bash
cd civex-hub
docker compose up --build
```

On first run, create the database tables and an admin user:

```bash
docker compose exec hub civexhub init-db
```

The hub is then available at **http://localhost:8001**.

## Configuration

All configuration is via environment variables.

| Variable | Required | Description |
|---|---|---|
| `CIVEXHUB_DATABASE_URL` | Yes | PostgreSQL connection string, e.g. `postgresql://user:pass@host/db` |
| `CIVEXHUB_SECRET_KEY` | Yes | Secret used to sign auth tokens — set a long random string in production |
| `CIVEXHUB_OBJECT_STORE` | No | `filesystem` (default) or `s3` |
| `CIVEXHUB_OBJECTS_DIR` | When `filesystem` | Path to store uploaded file objects |
| `CIVEXHUB_S3_BUCKET` | When `s3` | S3 bucket name |
| `CIVEXHUB_S3_PREFIX` | No | Key prefix inside the bucket (default: `objects/`) |
| `CIVEXHUB_S3_ENDPOINT_URL` | No | Custom endpoint for S3-compatible stores (e.g. MinIO) |
| `CIVEXHUB_S3_ACCESS_KEY` | No | S3 access key (falls back to instance role / env chain) |
| `CIVEXHUB_S3_SECRET_KEY` | No | S3 secret key |

## Manual installation

```bash
# civex must be installed first
pip install -e ..

pip install -e .            # filesystem object store
pip install -e ".[s3]"      # add S3 support

export CIVEXHUB_DATABASE_URL=postgresql://...
export CIVEXHUB_SECRET_KEY=...
export CIVEXHUB_OBJECTS_DIR=/path/to/objects

civexhub init-db
civexhub serve
```

## Connecting with the civex CLI

```bash
# Register an account
curl -X POST http://localhost:8001/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"secret"}'

# Log in (stores a token in ~/.civex/credentials)
civex auth login http://localhost:8001

# Push an existing local project
civex remote add origin http://localhost:8001
civex push

# Clone a repository
civex clone http://localhost:8001/alice/my-repo
```

## Access control

Repositories have three roles: **read**, **write**, and **admin**. Access can be granted to individual users, teams, or entire organisations.

```
POST /api/v1/repos/{owner}/{name}/access
{ "subject_type": "user" | "team" | "org", "subject_id": "<uuid>", "role": "read" | "write" | "admin" }
```

Organisation owners can add members and create teams via `/api/v1/orgs/{org_name}/members` and `/api/v1/orgs/{org_name}/teams`.

## Architecture

```
civexhub/
  src/civexhub/
    server/
      app.py          # FastAPI app factory; mounts frontend dist at /
      routers/
        auth.py       # POST /auth/register, /auth/tokens
        repos.py      # CRUD at /api/v1/repos
        sync.py       # transfer-pack (pull) and receive-pack (push) endpoints
        orgs.py       # orgs, teams, and repo access grants
        data.py       # browse repo data via the API
        settings.py   # user profile settings
    services/         # business logic (UserService, RepoService, OrgService, …)
    repositories/     # object store implementations (filesystem, S3)
    db/
      models.py       # SQLAlchemy ORM models (User, Repo, Org, Team, …)
      session.py      # engine factory; create_repo_schema() provisions per-repo schemas
  frontend/           # React + Vite + Tailwind
```

Each repository gets its own PostgreSQL schema (`repo_<uuid_hex>`), keeping civex tables fully isolated between repos.
