# Production readiness

This tracks what's left before civex (the local tool) and civex-hub (the
optional self-hosted server) are ready to run somewhere that matters. It
covers two different risk profiles:

- **`civex` core** — runs on the user's own machine, loopback-only by
  default (`src/civex/server/security.py`). Its production risk is mostly
  about *not corrupting or losing the user's local data across upgrades*,
  not network security.
- **`civex-hub`** — a network-facing, multi-tenant Postgres service people
  deploy with Docker. It has real auth, real attacker exposure, and needs a
  normal web-service security review.

Check items off as they land; keep this current rather than historical.

## Status

- [x] 1. Database migrations for `civex` core (see below) — `civex-hub` still open
- [ ] 1a. Database migrations for civex-hub's per-repo Postgres schemas
- [ ] 2. civex-hub auth hardening (rate limiting, password hashing cost)
- [ ] 3. Backup/restore story for both SQLite and civex-hub's Postgres
- [ ] 4. Release process (versioning, CHANGELOG discipline, alpha → beta gate)
- [ ] 5. Repo hygiene (stray `requirements.txt`, `build/`/`dist/` in git status)
- [ ] 6. CI hardening (dependency/security scanning, hub Docker build check)
- [x] 7. Test coverage baseline — see `tests/README.md` (~32%, steps 4-7 pending there)
- [x] 7a. Structured logging + secret redaction — already solid, see notes below
- [x] 7b. Opt-in error telemetry (Sentry) — already solid, see notes below

## 1. Database migrations

**civex core: done.** Alembic is now wired in (`src/civex/db/migrations/`,
`src/civex/db/migrate.py`). `ensure_schema_current(engine)` runs
automatically on every `build_local_context()` call (auto-upgrade on
connect, matching the local-first "just works" feel) and is cached per
engine so it's a no-op after the first check per process. It handles three
cases:

- **Brand new project** — `alembic upgrade head` creates every table and
  stamps `alembic_version` in one step.
- **Pre-existing install from before Alembic** — no `alembic_version`
  table, but `schemas` (and friends) already exist. Its shape already
  matches the baseline migration (the old ad hoc `ALTER TABLE` list kept it
  current on every connection), so it's stamped at head directly — we don't
  replay `create_table` against tables that already exist.
- **Already migrated** — `alembic upgrade head` applies whatever's newer
  than its current revision, same as any normal Alembic-managed app.

`civex db current` / `civex db migrate` are explicit escape hatches for
operators who want to check status or force the upgrade instead of relying
on the implicit on-connect check. Tests: `tests/db/test_migrate.py` covers
all three states plus the in-process caching behavior.

**civex-hub: still open.** Same problem, harder shape — one Postgres
*schema per repo*, so "run migrations" means iterating every tenant schema
rather than a single target DB. The civex-core Alembic setup can likely be
adapted (same models-diffing approach, `env.py` iterating
`search_path`/schema names instead of a single connection), but that's a
separate pass.

## 2. civex-hub auth hardening

civex-hub is the one component that's actually exposed to a network with
untrusted callers, so it deserves a normal web-app security pass:

- **Password hashing**: `pbkdf2_hmac("sha256", ..., 260_000)` iterations
  (`civex-hub/src/civexhub/services/user_service.py:16`). Workable, but
  OWASP's current guidance for PBKDF2-SHA256 is 600k+ iterations, or switch
  to argon2id. Raise the iteration count at minimum before a production
  deploy; migrating hash schemes later needs a re-hash-on-login path.
- **No rate limiting found** on `/auth/tokens` (login) or `/auth/register`
  (`civex-hub/src/civexhub/server/routers/auth.py`) — nothing stops
  password brute-forcing or registration spam. Needs per-IP/per-account
  throttling before this sits on the open internet.
- **`CIVEXHUB_SECRET_KEY`** is required and documented
  (`civex-hub/README.md`), but there's no startup check that rejects a
  default/empty/weak value — worth a hard fail on boot if unset or short.
- No CORS configuration was found in the hub app — confirm the deployed
  topology (same-origin frontend + reverse proxy) actually makes this a
  non-issue, and document the assumption if so.

## 3. Backup / restore

Neither `civex` nor `civex-hub` documents a backup procedure:

- **civex core**: a project's state is `_civex/` (SQLite DB + content-
  addressed `objects/`). Losing this is losing all local data — there's no
  documented `civex backup` / restore flow, and no guidance for the
  PostgreSQL-backed configuration either.
- **civex-hub**: relies entirely on the operator backing up Postgres and
  the object store (filesystem or S3) independently, with no restore
  runbook or consistency guarantee between "DB says this file exists" and
  "object store actually has it."

Document (or automate) a restore procedure and verify it actually works —
an untested backup is not a backup.

## 4. Release process

Currently: `pyproject.toml` classifies civex as `Development Status :: 3 -
Alpha`, versioned via `dynamic = ["version"]` (git-tag-driven, per recent
commits "Add version tag" / "Add PyPI release"). `CHANGELOG.md` has one
entry (v0.0.3). Before calling this production:

- Decide what "1.0" / "stable" means for this project and what's blocking
  it — the items in this doc are reasonable candidates.
- Keep `CHANGELOG.md` current per release (it's already started — just
  needs discipline going forward), and treat item 1 (migrations) as a
  changelog-worthy breaking-change category of its own.
- Bump the `Development Status` classifier off Alpha once the above lands,
  so `pip install civex` accurately signals maturity to new users.

## 5. Repo hygiene

A few things in the working tree that should be resolved before a
production cut, independent of code correctness:

- `requirements.txt` at the repo root looks like a stray `pip freeze` dump
  (pinned exact versions of FastAPI/pandas/etc.) sitting alongside
  `pyproject.toml`, which is the real dependency source of truth. If it's
  not used by anything (CI installs via `pip install -e ".[...]"`), delete
  it — a second, silently-drifting dependency list is a footgun.
  `build/` and `dist/` also currently show up in the working tree; confirm
  they're gitignored so packaging artifacts don't get committed by
  accident.
- Sample/scratch data files live at the repo root (`test_data.csv`,
  `PMC-BS_12_20210218-075000ch1min2.Table.1.selections.csv`,
  `pc_20210218_075000_min10_sel_01_PMC_12_Brazil.csv`, `Traces`,
  `sample_data`) — worth confirming these are intentional fixtures/examples
  and not accidental commits of local working data.

## 6. CI hardening

Current `.github/workflows/ci.yml` runs `ruff`, `mypy`, and `pytest` with a
coverage gate — solid baseline. Not yet covered:

- No dependency/vulnerability scanning (`pip-audit` or `safety` for civex,
  `npm audit` for the frontend).
- No CI job builds or smoke-tests the `civex-hub` Docker image, so a broken
  `Dockerfile`/`docker-compose.yml` wouldn't be caught until someone tries
  to deploy it.
- No frontend build check in CI (`npm run build` isn't run) — a TypeScript
  break in `frontend/` currently wouldn't fail CI. This overlaps with step 6
  of `tests/README.md` (frontend test setup) — the build check is cheaper
  and can land first.

## Already in good shape

Worth calling out so it doesn't get "fixed" again or re-litigated:

- **Observability** (`src/civex/observability.py`): structlog-based
  logging with a secrets-scrubbing processor (`_SENSITIVE_KEYS` covers
  `api_key`, `authorization`, `password`, `token`, `dsn`, etc.), rotating
  JSON file logs, and opt-in Sentry telemetry that's a strict no-op unless
  a DSN is configured. No changes needed here for production — just make
  sure operators know `CIVEX_LOG_JSON=1` / a Sentry DSN exist.
- **Loopback security model** (`src/civex/server/security.py`):
  `LocalGuardMiddleware` deliberately has no auth by design for the local
  server, with explicit DNS-rebinding and CSRF defenses, and an documented
  opt-out (`CIVEX_ALLOW_REMOTE=1`) that puts the network-security burden
  back on the operator (reverse proxy / firewall / VPN). This is a
  reasonable, intentional model for a `git`-like local tool — don't add
  auth to civex core itself; if remote exposure needs auth, that belongs in
  civex-hub, which already has it.
- **Test coverage baseline** — see `tests/README.md`; 90 tests, ~32%
  coverage, CI-gated at 30%. Steps 4-7 there (workflows/plugins, server
  routers, frontend tests, gate ratcheting) are the natural continuation
  and are tracked there, not duplicated here.
