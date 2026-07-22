# Production readiness

This tracks what's left before `civex` (the local tool, this repo) is ready
to call itself 1.0/stable. Its production risk is mostly about *not
corrupting or losing the user's local data across upgrades*, not network
security — it runs on the user's own machine, loopback-only by default
(`src/civex/server/security.py`).

**Scope note:** `civex-hub` (the optional self-hosted, multi-tenant Postgres
server) was removed from this repo in CIVEX-13 and now lives in its own
repo. Its readiness — auth hardening, per-tenant migrations, Postgres
backup/restore — is tracked there, not here. It is **not** a blocker for
this repo's 1.0.

Check items off as they land; keep this current rather than historical.

## Status

- [x] 1. Database migrations for `civex` core (see below)
- [ ] 3. Backup/restore story for SQLite (`_civex/` local data)
- [ ] 4. Release process (versioning, CHANGELOG discipline, alpha → beta gate) — see below
- [ ] 5. Repo hygiene (stray `requirements.txt`, `build/`/`dist/` in git status)
- [x] 6. CI hardening (dependency/security scanning, frontend build check)
- [x] 7. Test coverage baseline — see `tests/README.md` (~32%, steps 4-7 pending there)
- [x] 7a. Structured logging + secret redaction — already solid, see notes below
- [x] 7b. Opt-in error telemetry (Sentry) — already solid, see notes below

Numbering is kept stable against historical references (CIVEX-13 removed
items 1a/2 along with civex-hub itself).

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

## 3. Backup / restore

`civex` doesn't document a backup procedure. A project's state is
`_civex/` (SQLite DB + content-addressed `objects/`, or a PostgreSQL
connection for that configuration). Losing this is losing all local data —
there's no documented `civex backup` / restore flow, and no guidance for
the PostgreSQL-backed configuration either.

Document (or automate) a restore procedure and verify it actually works —
an untested backup is not a backup.

## 4. Release process

**Where this stands:** `pyproject.toml` classifies civex as
`Development Status :: 3 - Alpha`, versioned via `dynamic = ["version"]`
(setuptools-scm, driven entirely off `v*` git tags — this is already the
single source of truth for the package version; nothing else should
hardcode a version number, see "Consolidating version references" below).

Git tags currently run to v1.0.4 (several tags landed same-day in batches,
including a stray duplicate `V0.0.9`/`v0.0.9`), and until CIVEX-35, no
discipline tied a tag to a changelog entry — `CHANGELOG.md` sat frozen at
v0.0.3 while nineteen more tags shipped past it on PyPI. That's now fixed
with a single retroactive `CHANGELOG.md` entry consolidating everything
since v0.0.3 under v1.0.4 (see §4a). **The v1.0.x tag numbers should not be
read as a stability claim** — they reflect ad hoc tagging while exercising
the release pipeline, not a deliberate "this is stable" decision. Treat the
classifier and the criteria below, not the tag number, as the source of
truth for what "1.0" means.

### Definition of 1.0 / stable

Scoped to civex core only (civex-hub is a separate repo now, see the scope
note above). 1.0 means all of the following are true:

- [x] Migrations are handled safely across upgrades (item 1, done).
- [ ] A documented, verified backup/restore procedure exists (item 3).
- [ ] Every tagged release has a corresponding `CHANGELOG.md` entry, going
      forward, enforced in CI (item 4a below — this is CIVEX-35).
- [ ] Repo hygiene is clean — no stray dependency files or build artifacts
      in git status (item 5).
- [ ] CI has dependency/vulnerability scanning and a frontend build check
      (item 6).
- [x] A test coverage baseline exists and is CI-gated (item 7, done).

Once every box above is checked, bump the `Development Status` classifier
off Alpha (CIVEX-36) as part of the release that closes the last item —
not before, since `pip install civex` should only signal stability once it
is actually true.

### 4a. CHANGELOG discipline (CIVEX-35)

Going forward:

- Every `v*` tag must have a matching `## vX.Y.Z` entry in `CHANGELOG.md`
  before the tag is pushed. `.github/workflows/release.yml` enforces this —
  the release job fails fast (before building/publishing) if the pushed
  tag has no matching heading.
- Treat breaking changes — schema/migration changes (item 1) foremost among
  them — as their own changelog category so they're easy to scan for when
  upgrading, not buried in a generic "Changes" bullet list.
- Historical gap: v0.0.4 through v1.0.3 were never individually documented
  in `CHANGELOG.md` and are not being backfilled tag-by-tag (those releases
  predate any process, and reconstructing accurate per-tag notes now isn't
  worth the archaeology). Instead, everything that shipped across that
  range is folded into a single retroactive `v1.0.4` entry. Discipline
  applies starting from the next tag forward.

### Consolidating version references

The package version has exactly one source of truth: the `v*` git tag,
resolved by setuptools-scm into `civex.__version__`
(`src/civex/__init__.py`). Anything that needs "the current civex version"
at runtime should import `__version__` rather than hardcoding a literal —
two call sites (`src/civex/cli/dump.py`, `src/civex/server/routers/dump.py`)
were found hardcoding a stale `"0.1.0"` in exported dump files and have
been fixed to import `__version__` instead.

`frontend/package.json` has its own independent `"version"` field. It's
required by the `package.json` schema but isn't consumed anywhere (not
published to npm, not read by the app) — it's inert boilerplate, not a
second definition of the civex version, so it's left as-is rather than
wired up to something that doesn't need it.

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

**Done.** `.github/workflows/ci.yml` runs `ruff`, `mypy`, `pytest` with a
coverage gate, and now an `audit` job (`uv run pip-audit`, dev dependency
added in `pyproject.toml`) that fails the build on a known CVE in civex's
resolved dependencies. `.github/workflows/frontend-ci.yml` has a `build` job
(`npm run build`, i.e. `tsc -b && vite build`) that fails on a TypeScript
break, and an `audit` job (`npm audit --audit-level=high`) for the frontend.
Both audit jobs are also available locally via `make audit` (rolled into
`make check`).

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
