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

`project.frame(collection, schema)` gives the records of one kind as a pandas
DataFrame whose columns already have their types. It is the same table an
export writes (the same columns, the same rule for fields of the records
above and for links), with Python values instead of text:

```python
import civex

with civex.open() as project:
    samples = project.frame("survey-2024", "sample")

samples.dtypes
# id                  string
# depth              float64
# count                Int64      (whole numbers; a blank stays <NA>)
# taken    datetime64[UTC]      (date and time, in UTC)
# day           datetime64      (a date field that takes whole days)
# region            category      (a choice)
# site_name           string      (a field of the site each sample is inside)
# place               object      (the location as GeoJSON)
# place_lat, place_lon float64    (for points)
# audio               string      (where the file is on this computer)
```

What each kind of field becomes:

| Field | In the DataFrame |
|---|---|
| Whole number, decimal, true/false | `Int64`, `float64`, `boolean` (blanks stay blank) |
| Date | a date (`datetime64`) when the field takes whole days. A field that also takes a year or a month keeps its values as written (`"2019"`, `"2019-06"`), because a year is not its first day; `civex.domain.partial_dates.period(value)` gives the first and last day it covers |
| Date and time | `datetime64` in UTC (`samples.taken.dt.tz_convert("Europe/London")` for local time) |
| Location | the GeoJSON geometry, plus `<field>_lat` and `<field>_lon` for points (`geo="split"`, the default); `geo="geojson"` leaves out the two columns, `geo="wkt"` gives well-known text (`POINT (-3.41 56.12)`) for shapely or GeoPandas |
| File | the path of the file on this computer, ready for `open()` (`files="path"`, the default); `files="name"` gives its name. A file that isn't here right now (a drive not plugged in, files kept in a bucket, only on the server) gives its name |
| List of files, tags, links to several records | a list |
| Link to a record | the record's name (`references="name"`, the default) or its id (`references="id"`) |
| Choice | `category` |
| Text | `string` |

A file's path is where civex keeps it, named by its content, so it has no
extension: libraries that read the file's own header (soundfile, Pillow,
pandas' readers) open it as it is. Read it, never write to it.

**Columns.** `columns=[...]` picks and orders them. A column is a field of the
kind, a field of a record it sits inside (a sample inside a site has the
site's fields as columns, by their names), a field of the record a link
points at (`lab.title`), or one of `id`, `schema`, `parent_record_id`,
`created_at`, `updated_at`. Without `columns` the table is the id and every
field, those of the records above included. A name that isn't any of these
raises `ValidationError`.

```python
with civex.open() as project:
    df = project.frame(
        "survey-2024",
        "sample",
        columns=["id", "site_name", "place", "depth", "audio", "lab.title"],
        where={"field": "depth", "op": "gt", "value": 10},
    )

df.attrs["units"]   # {"depth": "m"}: each decimal field's unit
df.attrs["types"]   # {"depth": "float", "place": "geo", ...}: each column's civex type

import soundfile
for path in df.audio.dropna():
    signal, rate = soundfile.read(path)
```

A decimal field with a unit keeps its name as the column's; every value is in
that unit, which `df.attrs["units"]` names.

**Which records.** `where` is a filter, either the explorer's (a dict, as
saved in a view) or a list of `"field=value"` terms; `search="..."` and
`search_fields=[...]` look for text as the app's search box does; `within=`
takes a record id and keeps only what is beneath it. The collection may be
`None` for every collection.

`project.rows(...)` takes the same arguments and gives a list of dicts with
the same values (a `datetime.date`, a UTC `datetime`, a list), for code that
doesn't use pandas. Both read the records a page at a time, so the memory
used is the table's own. They are `project.file_access_svc.frame(query, ...)`
and `typed_rows(query, ...)` over a `RecordQuery`.

For records as civex holds them (field values as stored, names as keys),
`record_svc.iter_find(collection, schema_name=...)` returns them a page at a
time. To narrow it, pass `filters=["site=A3"]` (each entry is `field=value`)
together with `schema_name`. A field's name only means something within its
schema, so a filter without one raises `ValidationError`. `search="..."`
looks for text, ignoring case, in the records' values (text, numbers, list
items and file names; never a file's hash, a reference or a location), or the
start of a record's id. `search_fields=["site"]` looks only in those fields of
`schema_name`. `find`, `count`, `iter_find`, `find_by_schema` and
`count_by_schema_search` all take them, and match the same way.

## Summaries

`record_svc.summarise(query, request)` groups the records a `RecordQuery`
lists and works out measures over each group, in the database (one query,
however many records). It is what the explorer's **Summary** and
`civex record summarise` use:

```python
import civex
from civex.domain.query import RecordQuery
from civex.domain.summary import GroupBy, Measure, SummaryRequest

with civex.open() as project:
    result = project.record_svc.summarise(
        RecordQuery(dataset="survey-2024", schema="sample"),
        SummaryRequest(
            group_by=[GroupBy("region", schema="site"), GroupBy("taken", bucket="month")],
            measures=[Measure("count"), Measure("mean", "depth")],
        ),
    )
    for row in result.rows:
        print([g.label for g in row.groups], row.values)
    print("total", result.total)
```

A `GroupBy` names a field of the kind summarised, or of a kind above it
(`schema=`); `bucket` (year, month, week, day) groups a date, `bin` a number
into ranges that wide. A `Measure` is `count` (records) or one of `filled`,
`distinct`, `min`, `max`, `mean`, `sum` over a field. Each group value carries
`lower`/`upper` for a range or period, and each row `where`, the filter tree
that lists exactly its records (pass it as `filter_tree`). `parse_group_by`
and `parse_measure` read the CLI's written forms (`site.region`,
`taken:month`, `mean:depth`).

## Locations

`record_svc.points(query, field, schema=None, limit=10_000)` gives where the
records a `RecordQuery` lists are: each one with a value in the location
field `field` (of the kind listed, or of `schema`, a kind above it), with its
id, its name and the GeoJSON geometry, oldest first. It is what the
explorer's **Map** draws, and a quick way into a plotting library:

```python
import civex
from civex.domain.query import RecordQuery

with civex.open() as project:
    found = project.record_svc.points(
        RecordQuery(dataset="survey-2024", schema="sample"), "place", schema="site"
    )
    for p in found.points:
        print(p.name, p.geometry["type"], p.geometry["coordinates"])
    if found.truncated:
        print(f"first {len(found.points)} of {found.total}")
```

## Checking the data

`quality_svc.check(query)` says what in the records a `RecordQuery` lists
needs a look, per kind and field (values their field's rules now refuse,
required fields left empty, shared unique keys, broken links, missing files),
and `quality_svc.records_with(query, issue, field=...)` lists exactly the
records with one issue, ready for `record_svc.bulk_edit(..., ids=...)`:

```python
import civex
from civex.domain.query import RecordQuery

with civex.open() as project:
    query = RecordQuery(dataset="survey-2024", schema="sample")
    for kind in project.quality_svc.check(query).kinds:
        for line in kind.issues:
            print(kind.schema, line.field, line.issue, line.count)
    found, total = project.quality_svc.records_with(
        query, "breaks_rule", field="depth", limit=1000
    )
    project.record_svc.bulk_edit({"depth": None}, ids=[f.record_id for f in found])
```

`quality_svc.check_field(schema, field, restrictions={...})` counts what a
rule would leave behind before you change it.

## Review status and notes

`record_svc.set_review(status, ids=... | query=...)` marks records as
`needs_check`, `checked` or `none`, as you, now (`dry_run=True` only counts);
`note_svc` adds, lists, resolves and deletes the notes left on a record, and
counts the open ones among the records a query lists:

```python
with civex.open() as project:
    query = RecordQuery(dataset="survey-2024", schema="sample")
    project.record_svc.set_review("needs_check", query=query)
    project.note_svc.add("f623", "depth looks off, re-check the calibration")
    print(project.note_svc.open_notes(query).notes)
    waiting = RecordQuery(
        dataset="survey-2024",
        schema="sample",
        filter_tree={"field": "@review", "op": "eq", "value": "needs_check"},
    )
```

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
| `record_svc` | Records: find, summarise, points, add, patch, update, delete, restore, move |
| `file_svc` | Storing and reading files |
| `view_svc` | Saved views |
| `file_access_svc` | Exports of files and tables; `frame` and `typed_rows` |
| `history_svc` | History and revert |
| `bundle_svc` | Bundles for moving data between projects |
| `config` | The project's settings and its folder (`config.project_root`) |

These are the methods the command line and the app call, and they are
documented in their docstrings (`help(project.record_svc.patch)`).
