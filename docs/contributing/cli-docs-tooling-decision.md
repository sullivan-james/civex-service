# CLI docs tooling decision

The generated CLI reference (`docs/_gen/_cli.py`, added by a later ticket in
the Docs Epic C series) is a small custom generator instead of an existing
mkdocs/Typer plugin. This page records why, so the two obvious "just use a
library" options don't get re-litigated or re-discovered from scratch.

## Rejected: `mkdocs-click`

Structurally impossible, not merely risky. Typer 0.27 vendors a full Click
fork under `typer._click/` (its own `core.py`, `parser.py`, `LICENSE.txt`)
and declares no dependency on the PyPI `click` package — the `click 8.4.2`
present in `uv.lock` is a transitive dependency of uvicorn and unrelated to
Typer's command objects. Verified directly:

```
typer 0.27.0 | click 8.4.2
type: (TyperGroup, typer._click.core.Command, abc.ABC)
isinstance click.Group:       False
isinstance click.BaseCommand: False
```

`mkdocs-click`'s loader does `isinstance(command, click.BaseCommand)` and
recurses with `isinstance(command, click.Group)`; both are `False` against a
Typer app's command tree, so it raises on load. There's no shim that fixes
this short of Typer depending on real Click, which it doesn't.

## Rejected: `typer utils docs`

`.venv/bin/typer` exists and `typer civex.main utils docs` does produce
output with correct recursion (1,531 lines for this app), but it's unusable
as-is:

- Emits all five `hidden=True` plumbing commands (`transfer-pack`,
  `receive-pack`, `head-seq`, `get-object`, `put-object`) both in the index
  and as full sections, with no flag to exclude them.
- HTML-escapes apostrophes in help text.
- Produces one monolithic page, which can't be split across nav entries
  (one page per sub-app is required — see the parent epic's definition of
  done).

## Rejected: pinning `typer<0.16` to get real Click back

Downgrading the CLI framework to satisfy a docs plugin is backwards. All 68
commands are written against Typer 0.27's help rendering; pinning back to
recover `mkdocs-click` compatibility would mean maintaining the CLI against
an older, unrelated-to-docs constraint indefinitely, for the benefit of a
tool that only runs at doc-build time.

## Decision

Write a small custom generator (~150 lines) against `typer._click`, modelled
on `typer.cli.get_docs_for_click` (importable and callable — a good
reference implementation, just with the wrong policy for this repo) but
with the exclusions above fixed: skip `hidden` commands, emit one page per
sub-app, and fence indented example blocks instead of relying on `\b`
(Typer's markdown emitter passes `\b` through as a literal `\x08` control
character under `rich_markup_mode="rich"`, which renders as a visible glyph
rather than suppressing line-wrapping the way Click's own help formatter
does).
