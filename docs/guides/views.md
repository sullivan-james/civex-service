# Saved filters

A **saved filter** keeps which records a list shows: its filter, search and
sort (and the columns it was saved with). Saved filters show as chips above a
list of records, so the lists a team keeps reaching for are one click away. A
saved filter belongs to a kind of record, not to a person or a collection: one
on `sample` works on samples in every collection, for everyone. (The command
line and the API call them views.)

## Save one

Set up a list the way you want it, with **+ Filter** or by clicking bars in
the [charts](collections-and-records.md#charts), then **Save this filter**. It
keeps:

- **Filters**: an AND/OR tree that may test this kind's fields, a parent's
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
  **Save this filter** makes another.
- The **⋮** beside an applied one renames or deletes it. Deleting a saved
  filter never touches records.

Saved things are marked with an icon and a word wherever they are listed (the
bar above the records, pinned items, the Ctrl+K palette): a **Saved filter**
or an **Export** (an export definition).

## The Analytics page

**Analytics** is one page for the whole project. Everyone sees the same page,
it is in Activity, and it syncs. It holds **cards**: charts of records, and
the built-in charts (records, storage, workflow runs, activity, AI use).

A chart gets here from a list of records: in a chart's menu, **Add to
Analytics page**. The card keeps the chart and the records it counted (the
kind, the collection, the record they were inside, the search and the
filter), and draws them as they are now. **Records** on a card opens that
list; **Open** shows the chart large with its numbers. **For** at the top
narrows every chart to one collection. The filter bar applies to the built-in
charts.

Anyone who may change records somewhere may press **Edit page**. While
editing, you can drag a card or use its arrows to move it, choose **Half** or
**Full width**, give it a title, take it off the page, and **Add a card** for
a built-in chart. **Done** saves the page for everyone as one change;
**Cancel** leaves it as it was. A card whose kind of record or collection is
gone stays and says so until someone removes it.

```bash
civex dashboard show
civex dashboard add --schema sample --by site --measure mean:depth --in survey --size wide
civex dashboard add --schema sample --map position
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
