# Views

A **view** is a saved filter, column set and sort on a schema (a schema). Views show as
chips above a list of records, so the lists a team keeps reaching for are one
click away. A view belongs to its schema, not to a person or a collection: a view
on `sample` works on samples in every collection, for everyone.

## Save one

Set up a list in a collection the way you want it, then **Save as view…**. It
keeps:

- **Filters**: an AND/OR tree that may test this schema's fields, a parent's
  fields, or any child's ("visits that have a sample whose `depth` is
  empty").
- **Columns**, in order: including parents' fields and one hop through a
  reference (`species.common`).
- **Sort**: one field, ascending or descending.

Any name works except one containing `/`, `\` or control characters
(`Needs review (QC)` is fine).

## Use, change, remove

- Click a chip to apply it, and click again to drop it.
- Change the list and the chip shows **modified**. **Save** overwrites, and
  **Save as view…** makes another.
- The **⋮** beside an applied view renames or deletes it. Deleting a view never
  touches records.

## Saved analyses

A **saved analysis** is a view that also keeps a summary: what is worked out,
how it is grouped, table or chart, the sort, and where it was made (the
collection, the record and the search). Make one from the explorer's
**Summary** with **Save analysis…**. If you opened an analysis, you can update
it or **Save as new**.

Saved things are marked by what you get when you open them, with an icon and
a word: a **List** (a plain view: records, filtered and sorted), an
**Analysis** (opens on its summary) or an **Export** (an export definition).
The same marks show in the bar above the records, in pinned items and in the
Ctrl+K palette. An analysis can be pinned like any view, and it can be put on
the [Analytics page](#the-analytics-page). From an analysis, **Export ›
Export these records…** exports the records it summarises.

Saving an analysis checks the summary first, so one that could not be worked
out (a field that doesn't exist, an average of text) is refused.

```bash
civex view save-analysis sample "Depth by site" --by site --by taken:month \
  --measure count --measure mean:depth --in survey --chart
civex view show sample "Depth by site"   # its summary, worked out now
```

The API is the view's own: `summary` on `POST`/`PATCH
/api/schemas/{schema}/views[/{name}]` (null makes it a plain view again), and
`GET /api/schemas/{schema}/views/{name}/summary` works it out.

## The Analytics page

**Analytics** is one page for the whole project. Everyone sees the same page,
it is in Activity, and it syncs. It holds **cards**: saved analyses, drawn as
their table or chart with **Open in explorer**, and the built-in charts
(records, storage, workflow runs, activity, AI use). The filter bar at the top
applies to the built-in charts.

Anyone who may change records somewhere may press **Edit page**. While
editing, you can:

- drag a card by its handle, or use its arrows, to move it;
- choose **Half** or **Full width**;
- give it a title of its own;
- take it off the page;
- **Add a card**: a saved analysis or a built-in chart.

**Done** saves the page for everyone as one change; **Cancel** leaves it as it
was. A card whose analysis was deleted stays and says so until someone removes
it. If the page is empty, it explains how to make an analysis.

```bash
civex dashboard show
civex dashboard add --analysis "sample/Depth by site" --size wide
civex dashboard add --widget storage --at 1
civex dashboard remove widget-storage
```

## Export one

```bash
civex view export sample "Needs review (QC)"                 # → Needs review (QC).csv
civex view export sample "Needs review (QC)" --format xlsx
civex view export sample qc --output qc.csv
```

Formats: `csv`, `tsv`, `xlsx`, `json`, `jsonl`. If the view has file columns,
the output is a zip of the table plus the files, and each file cell holds the
file's path inside the zip. Joined columns are named `species.common`, and in JSON
they nest as `{"species": {"common": …}}`.

A view can also drive a folder export or a move:
`civex files export --view sample/qc`, `civex files gather --view sample/qc --to archive`.
