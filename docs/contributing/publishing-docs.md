# Publishing the docs site

The docs are plain static HTML — `mkdocs build` renders `docs/` into a
self-contained `site/` directory with no server-side dependencies. Nothing
here is tied to GitHub Pages: `mkdocs.yml` sets `use_directory_urls: false`
specifically so the output works unmodified from nginx, Apache, an S3
bucket, a USB stick, or `file://` with no web server at all.

## What CI does

`.github/workflows/docs.yml` builds the site on every pull request and on
every push to `main` that touches `docs/**`, `mkdocs.yml`, `README.md`,
`src/**`, or `pyproject.toml`:

```bash
uv sync --extra server --extra docs
uv run mkdocs build --strict
```

The resulting `site/` directory is uploaded as the `docs-site` workflow
artifact on every run, so a PR's build can be downloaded and inspected
before it merges.

On `main`, the same job adds a publish step:

```bash
rsync -az --delete site/ "$DOCS_HOST:$DOCS_PATH"
```

`DOCS_HOST` and `DOCS_PATH` are repository secrets, not workflow config —
the workflow doesn't know or care what's on the other end. If `DOCS_HOST`
is unset, the publish step is skipped and the job still succeeds; the
build and artifact upload are unaffected. Swapping `rsync` for `aws s3
sync` (or any other "unpack `site/` into a webroot" mechanism) only
requires changing that one step.

## Building locally

```bash
make docs        # mkdocs serve, with live reload
make docs-build  # one-shot build into site/, what CI runs
```

`site/` opens directly from `file://` with no network access — there's no
dependency on a running server to preview the output.
