# Views

A **view** is a saved filter, column set and sort on a schema. Views show as
chips above a list of records, so the lists a team keeps reaching for are one
click away. A view belongs to its schema, not to a person or a collection: a view
on `recording` works on recordings in every collection, for everyone.

## Save one

Set up a list in a collection the way you want it, then **Save as view…**. It
keeps:

- **Filters**: an AND/OR tree that may test this schema's fields, a parent's
  fields, or any child's ("encounters that have a selection whose `quality` is
  empty").
- **Columns**, in order: including parents' fields and one hop through a
  reference (`site.code`).
- **Sort**: one field, ascending or descending.

Any name works except one containing `/`, `\` or control characters
(`Needs review (QC)` is fine).

## Use, change, remove

- Click a chip to apply it, and click again to drop it.
- Change the list and the chip shows **modified**. **Save** overwrites, and
  **Save as view…** makes another.
- The **⋮** beside an applied view renames or deletes it. Deleting a view never
  touches records.

## Export one

```bash
civex view export recording "Needs review (QC)"                 # → Needs review (QC).csv
civex view export recording "Needs review (QC)" --format xlsx
civex view export recording qc --output qc.csv
```

Formats: `csv`, `tsv`, `xlsx`, `json`, `jsonl`. If the view has file columns,
the output is a zip of the table plus the files, and each file cell holds the
file's path inside the zip. Joined columns are named `site.code`, and in JSON
they nest as `{"site": {"code": …}}`.

A view can also drive a folder export or a move:
`civex files export --view recording/qc`, `civex files gather --view recording/qc --to archive`.
