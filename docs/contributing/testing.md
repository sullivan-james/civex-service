# Testing

The repo has ~11.6k lines of Python source. This page tracks the plan for
test coverage and describes the current test structure; keep it current as
steps land rather than letting it go stale.

## Status

- [x] 1. Add coverage tooling
- [x] 2. Restructure `tests/` to mirror `src/civex/`, add shared fixtures
- [x] 3. Cover data integrity logic (restrictions, inheritance, file storage)
- [ ] 4. Cover workflow execution and built-in plugins
- [ ] 5. Cover the untested server routers
- [ ] 6. Stand up frontend testing (Vitest + React Testing Library)
- [ ] 7. CI wiring for coverage gate + frontend test job

## 1. Coverage tooling

(The `httpx2` pin in the `dev` extra initially looked like a typo for `httpx`
— it isn't. Starlette's `TestClient` now imports `httpx2` first and falls
back to `httpx` with a deprecation warning, so the existing pin was correct
and was left alone.)

`pytest-cov` and a `[tool.coverage.run]` config (`source = civex`) are wired
in. CI runs `pytest --cov=civex --cov-report=term-missing --cov-fail-under=30`
(see `make test`). Coverage was ~28% before this plan and is ~32% after
step 3; the threshold is set a few points below the measured value so
normal variance doesn't flake CI. Ratchet it up as steps 4-6 land — don't
raise it faster than real coverage grows, or CI starts failing for the
wrong reason. See `PRODUCTION_READINESS.md` at the repo root for how this
fits into the broader 1.0 checklist — it's a root-level tracking doc, kept
outside the docs site nav since it's a running punch list rather than
reference documentation.

`tests/bench_indexes.py` was a benchmark script living in `tests/`, excluded
from CI via `--ignore`. It lives in `benchmarks/` now, so `tests/` only
contains actual tests and nothing needs special-casing in the pytest
invocation.

## 2. Test structure

```
tests/
  conftest.py   # shared fixtures: ctx (AppContext), project_dir, client, factories
  test_smoke.py # end-to-end CLI/API happy path, trimmed to the essentials
  cli/          # CLI-level tests (Typer CliRunner)
  services/     # service-layer tests (AppContext, no CLI/HTTP)
  server/       # FastAPI router tests (TestClient)
  db/           # Alembic migration tests (bare engines, no AppContext)
  workflows/    # executor + trigger tests (not yet created — step 4)
  plugins/      # one file per built-in plugin (not yet created — step 4)
```

`conftest.py` provides:

- `project_dir` — inits a temp civex project via the CLI (same as the
  existing smoke-test fixture) and chdirs into it.
- `ctx` — builds an `AppContext` directly via `build_local_context()` against
  that temp project, bypassing the CLI/HTTP layers so service tests are fast
  and don't need to parse Rich console output. Callers must `ctx.commit()`
  when a test needs data visible across separate repo calls.
- `make_schema` / `make_collection` / `make_record` — small factories to cut
  boilerplate in tests that just need "a schema with one field" or "a
  collection with a record in it."

## 3. Data integrity coverage

- `tests/services/test_record_service_restrictions.py` — parametrized
  `_check_restrictions` coverage across every dtype × restriction key
  combination (`min`/`max` on numeric and date/datetime, `choices`/
  `max_length` on string, `accept`/`max_size` on file), including a
  regression test showing why date/datetime bounds must compare parsed
  objects rather than raw ISO strings, plus the naive-datetime-assumed-UTC
  rule in `_parse_datetime`.
- `tests/domain/test_timezones.py` and `tests/server/test_collection_timezone_api.py`
  — timezone resolution (field > collection > UTC), DST gap/overlap rejection,
  and that the API write path normalises datetimes. The DST cases are mirrored
  by `frontend/src/utils/dates.test.ts` so the two implementations stay in step.
- `tests/services/test_record_service_integration.py` — the `reference`
  dtype's `schema` restriction (enforced in `coerce_value`, not
  `_check_restrictions`) and the `record_created` + `record_updated`
  dual-trigger-on-create behavior described in the root `CLAUDE.md`.
- `tests/services/test_schema_service.py` — `collect_fields()` multi-level
  inheritance, own-field-shadows-parent-field-of-same-name, and field
  ordering (own fields first, then inherited).
- `tests/services/test_file_service.py` — sha256-based dedup on `put()`
  (writing the same bytes twice returns the same ref pointing at the same
  object path), `retrieve()`/`object_path()` behavior, and volume-queue
  fallback when the first volume is full.

## Remaining steps (not yet started)

**4. Workflows and plugins** — executor topological sort, cycle detection,
`step_id.output_name` resolution, manual-run `__input__` path, and one test
per built-in plugin (especially the regex-heavy `extract_from_filename` and
`match_files_to_records`).

**5. Server routers** — `datasets`, `files`, `jobs`, `plugins`, `workflows`,
`store`, `dump` have no tests. `ai.py` (873 lines, the largest
untested router) needs its outbound `httpx` calls mocked so tests don't hit
real providers.

**6. Frontend** — no Vitest/RTL setup exists yet. Priority: `DynamicField`
(restriction-aware rendering) and `JobsTable` (pagination state), since
`CLAUDE.md` calls out both as shared components other code must not
duplicate — regressions there are the most cross-cutting.

**7. CI gate** — once steps 4-6 produce a real coverage number, raise
`--cov-fail-under` to match, and add a `frontend-test` CI job running
`npm run test` in `frontend/`.

## Running tests

```bash
uv run pytest tests/                                             # all tests  (== make test)
uv run pytest tests/test_smoke.py::test_init_creates_civex_dir   # a single test
```
