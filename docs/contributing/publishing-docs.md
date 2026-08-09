# Publishing the docs site

The docs are plain static HTML — `mkdocs build` renders `docs/` into a
self-contained `site/` directory with no server-side dependencies.
`mkdocs.yml` sets `use_directory_urls: false` specifically so the output
works unmodified from GitHub Pages, nginx, an S3 bucket, a USB stick, or
`file://` with no web server at all.

This page is maintainer-only: `contributing/` is listed under
`exclude_docs` in `mkdocs.yml`, so nothing here ships to the public site.

## Where the site is served from

`civex-service` is private, and GitHub Pages cannot serve a site from a
private repository without a paid plan. So the built HTML is force-pushed
to a separate **public** mirror, `CivexData/civex-docs`, and Pages serves
that:

```
civex-service (private)  ──build──>  site/  ──force-push──>  civex-docs (public, gh-pages)
                                                                      │
                                                                      └──> https://civexdata.github.io/civex-docs/
```

The mirror holds *generated HTML only* — never source, never `docs/`
markdown. Its history is replaced on every deploy.

## What CI does

`.github/workflows/docs.yml` builds the site on every pull request and on
every push to `main` that touches `docs/**`, `mkdocs.yml`, `README.md`,
`src/**`, or `pyproject.toml`:

```bash
uv sync --extra server --extra docs
uv run mkdocs build --strict
```

The resulting `site/` directory is uploaded as the `docs-site` workflow
artifact on every run. **That artifact is the PR preview mechanism** —
download it from the run's summary page and open `index.html`; there are
no per-PR preview URLs.

On `main`, the same job adds a publish step that force-pushes `site/` to
`civex-docs@gh-pages`. Two details in that step are load-bearing:

- **`touch .nojekyll`** — GitHub Pages runs Jekyll by default, which
  silently drops paths containing underscores. Without this file, parts
  of the Material theme's `assets/` tree 404 and the site renders
  unstyled.
- **The commit message is a bare `"Docs build"`**, with no `${GITHUB_SHA}`
  interpolation. Interpolating it would publish this private repo's
  commit SHAs into a public repo's permanent history.

The step deliberately has **no `if: secrets.X != ''` guard**. The publish
step it replaced was gated that way, `DOCS_HOST` was never set, and the
job reported success while publishing nothing for months. A missing token
now fails the job.

## Required secret

| Secret | Scope |
|---|---|
| `DOCS_PUSH_TOKEN` | A **fine-grained** PAT scoped to `CivexData/civex-docs` only, permission `Contents: Read and write`. Not a classic token, not org-wide. |

Set with `gh secret set DOCS_PUSH_TOKEN --repo CivexData/civex-service`.

## What is excluded from the published site

`exclude_docs` in `mkdocs.yml` drops three trees from the build:

| Path | Why |
|---|---|
| `_gen/` | Generator scripts, not pages |
| `_prose/` | Prose halves spliced into generated plugin pages |
| `contributing/` | Maintainer-only — including this page, the deploy mechanism above, and the internal ADR in `cli-docs-tooling-decision.md` |

If you add a page under `contributing/`, do **not** add it to `nav` —
`mkdocs build --strict` fails on a nav entry pointing at an excluded file.
Link it from `CONTRIBUTING.md` instead, which uses repo-relative paths
that resolve on GitHub.

`mkdocs.yml` also deliberately omits `repo_url` and `edit_uri`. Both would
render links to the private `civex-service` repo in the site header, which
404 for every visitor.

## Building locally

```bash
make docs        # mkdocs serve, with live reload
make docs-build  # one-shot build into site/, what CI runs
```

`site/` opens directly from `file://` with no network access.

Before a change that touches what gets published, sweep the output — it is
about to become world-readable and permanent in the mirror's history:

```bash
grep -rE "CIVEX-[0-9]+" site/ | wc -l   # expect 0
grep -ri "civex-service" site/ | wc -l  # expect 0
```

## Moving to docs.civex.dev later

The github.io URL is a starting point, not a commitment. To switch:

1. Add a file `docs/CNAME` containing `docs.civex.dev` (MkDocs copies it
   verbatim into `site/`).
2. Set `site_url: https://docs.civex.dev/` in `mkdocs.yml`.
3. Add a DNS `CNAME` record: `docs` → `civexdata.github.io`.
4. On `civex-docs`: Settings → Pages → Custom domain → `docs.civex.dev`,
   then tick **Enforce HTTPS**.
5. Update the three hardcoded doc links in `civex-plugin-sdk/README.md`.

Because `use_directory_urls: false` keeps every internal link relative,
nothing else changes — the same build works at either address.
