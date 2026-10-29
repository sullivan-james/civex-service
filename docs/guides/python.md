# Using civex from Python

A script, a notebook or a pipeline step can open a project directly with
`civex.open()`. Nothing else needs to be running: no server and no app. You
get the same services the `civex` command and the app use, in your own process,
so whatever works there works here, with the same checks, history and
automations.

```python
import civex

with civex.open("~/fieldwork") as project:
    for page in project.record_svc.iter_find("survey-2024", schema_name="sample"):
        for record in page:
            print(record.id, record.data)
```

`civex.open(path)` finds the project at `path` or in a folder above it (like
`git` does), and opens the one around the current directory when no path is
given.

## Saving changes

Inside a `with` block, everything the block did is saved when it finishes, and
nothing is saved when it raises. A failed pipeline step therefore leaves the
project as it was:

```python
with civex.open() as project:
    project.record_svc.add("survey-2024", "sample", {"depth": 1.5, "site": "A3"})
    project.record_svc.add("survey-2024", "sample", {"depth": 2.0, "site": "A4"})
# both saved here, or neither
```

Without a `with` block, call `project.commit()` to save and `project.close()`
when you're done.

## Reading into pandas

`iter_find` returns records a page at a time, so large collections never have
to fit in memory at once. Each record's `data` uses field names as its keys:

```python
import pandas as pd
import civex

with civex.open() as project:
    rows = [
        {"id": str(r.id), **r.data}
        for page in project.record_svc.iter_find("survey-2024", schema_name="sample")
        for r in page
    ]
samples = pd.DataFrame(rows)
```

To narrow the list, pass `filters=["site=A3"]` (each entry is `field=value`)
together with `schema_name`. A field's name only means something within its
schema, so a filter without one raises `ValidationError`. `search="..."`
searches the records' text.

## Writing results back

- `record_svc.add(collection, schema, data, parent_record_id=...)` adds a
  record (inside another record when the schema is a child kind).
- `record_svc.patch(record_id, {"field": value})` changes only those fields
  and writes nothing when they already hold those values.
- `record_svc.update(record_id, data)` replaces **all** of a record's data, so
  any field you leave out is cleared. Use `patch` unless that is what you want.

To attach a file, store it first and then put its reference in a `file`
field:

```python
from pathlib import Path

with civex.open() as project:
    survey = project.dataset_svc.get("survey-2024")
    ref = project.file_svc.store(Path("out/profile.png"), collection_id=str(survey.id))
    project.record_svc.patch(record_id, {"profile": ref.to_dict()})
```

Values are checked as they would be in the app. A value a field doesn't allow
raises `civex.domain.exceptions.ValidationError`, and a name that doesn't exist
raises `NotFoundError`.

## Automations

Adding or changing a record queues any workflow whose trigger matches, just
as an edit in the app does. The runs happen wherever automations are being
run: the app (`civex serve`) runs them on its own, and without it
`civex automation run` runs what's waiting.

## Alongside the app and the command line

A script can work on a project while the app is open or a `civex` command is
running. On SQLite, a write waits briefly for another one to finish. Keep each
`with` block short in a long-running script, because the block holds its
changes until it ends.

## What's there

The opened project has one service per area, for example:

| Attribute | For |
|---|---|
| `schema_svc` | Schemas and their fields |
| `dataset_svc` | Collections |
| `record_svc` | Records: find, add, patch, update, delete, restore, move |
| `file_svc` | Storing and reading files |
| `view_svc` | Saved views |
| `file_access_svc` | Exports of files and tables |
| `history_svc` | History and revert |
| `bundle_svc` | Bundles for moving data between projects |
| `config` | The project's settings and its folder (`config.project_root`) |

These are the methods the command line and the app call, and they are
documented in their docstrings (`help(project.record_svc.patch)`).
