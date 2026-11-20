# Collections & records

A **collection** is the binder: it holds records of any
[schema](schemas-and-fields.md), one collection per study or season, as suits
you, and says who may link to them. A **record** is one filled-in form of a schema: this
site, this sample. If the two blur together, read
[Schemas, collections and records](../getting-started/concepts.md).

## Collections

```bash
civex collection create survey-2024 --description "2024 field season" \
  --timezone Europe/London
civex collection show survey-2024
```

```text
survey-2024
  Records  0
  2024 field season
  Timezone  Europe/London
  Scope     local
```

| Setting | Means |
|---|---|
| **Scope** (`--scope`) | `local` (default): only records here can link to these. `global`: any collection can, for shared lists such as species, instruments or people |
| **Timezone** (`--timezone`) | How times without a UTC offset are read and shown. See [Times and timezones](schemas-and-fields.md#times-and-timezones) |

```bash
civex collection create taxonomy --scope global
civex collection list
```

A `reference` field links to records in its own collection or in a global one,
never in another local collection. A global collection that others link to can't
be made local or deleted.

Every collection holds records of every schema, including one made after the
collection: there is no list of schemas on a collection to keep up to date.

**In the app:** **Collections → New collection**, and **Edit** on a collection's
page.

## Adding records

=== "Web UI"
    In a collection, the **New** menu lists the schemas you can add here
    (**New ▸ New site**). Inside a record, it lists the types that go inside it
    (inside a visit: **New ▸ New sample**). This is the step you repeat; the
    schema is made once. **Add and add another** saves
    and gives you a blank form. A folder of files comes in through a workflow:
    see [Import files](../how-to/import-data.md).

=== "CLI"
    ```bash
    civex record add --to survey-2024 --schema sample
    ```

    ```text
      Parent record ID (visit): 2d69dc46
      number (integer) []: 3
      depth (float) []: 12.5
      taken_at (datetime) []:
      photo (file) []: /data/IMG_0412.jpg
      reading (file) []:
    Added record f623c8d7-eb75-41e1-b2ec-d6feb7f02f7a.
    ```

    For a type that goes inside another it asks for the parent record first. A
    file field takes a path, and a reference takes a record id or any unique
    prefix of one.

## Finding records

```bash
civex record find --in survey-2024 --schema sample --where "number=3" --limit 20
civex record show f623
```

```text
Record f623c8d7-eb75-41e1-b2ec-d6feb7f02f7a
  Schema    sample
  Parent    2d69dc46 (visit)
  Created   2026-10-09 11:11 UTC
Field     Value
number    3
depth     12.5
photo     IMG_0412.jpg
name      North Ridge  (↑ site)
```

`--where` repeats, and all conditions must match. Every record has a UUID, and
any unique prefix of it works wherever an id is asked for.

### The explorer

A collection's page (and a record's **Contains** tab) is one explorer:

- **Levels:** the collection's schemas top-down (Site → Visit → Sample),
  with counts. A row shows its children ("3 visits →"). Click to go down, and
  use the trail to go back up.
- **Search** is scoped to where you are. It looks, ignoring case, in what the
  records hold: text, numbers, the items of a list (tags, choices) and the
  names of files. It never matches a file's hash, a reference or a location,
  so a short search like `a3` finds only records that show `a3`. Typing the
  start of a record's id (four characters or more) finds that record too.
  Beside the box, **In all fields** can be narrowed to one field of the kind
  listed (`qin` in the address).
- **+ Filter** builds AND/OR conditions on this level's fields, a parent's, or
  any child's: "Visits that have a Sample whose `depth` is empty" is one
  condition. Reference values are picked by name.
- **Saved filters** are the schema's [views](views.md). **Save as view…** saves
  yours, and everyone sees it.
- **Columns** include parents' fields and fields through a reference. Click a
  header to sort.
- **Export** takes exactly the rows listed or ticked. See
  [Get files out](../how-to/export-files.md).
- **Records | Their files** switches to the files of what's listed. See
  [Files](files.md#working-on-many-files-their-files). **Summary** counts and
  averages them by group, as a table or a chart: see [Summaries](#summaries).
  **Map** shows them on a map: see [On a map](#on-a-map).
- Tick rows (shift-click for a range) to **Delete** or **Run workflow on N**.
  Ticking a whole page offers **Select all N matching**.

Everything is in the address, so a filtered list can be bookmarked and Back
undoes a step. Scripts get the same from `GET /api/records` with `schema`,
`within`, `filter`, `sort`, `search` and `search_field` (repeatable: the fields
to search in), and from `civex record find --in <collection> --schema <kind>
--search <text> [--search-field <field>]`.

A record's **Referenced by** section counts the records linking to it, per
collection, schema and field (`GET /api/records/{id}/referrers`).

### Summaries

**Records | Their files | Summary** switches the explorer to a summary of
exactly what it lists (the same level, filters, search and saved filter):

- **Group by…** a field of the kind listed, or of a kind above it ("Samples
  by Site › Region"), up to three at once. A date groups by each value or by
  year, month, week (starting Monday) or day; a date and time does the same
  in its field's time zone, else the collection's, else UTC. A number groups
  by each value or into ranges of a width you choose ("0 to under 5 m"). A
  list (tags, links to records) puts a record in a group for each item, so
  the groups can add up to more than the total.
- **Show** what to work out: **Records** (how many), and per field what its
  type allows: **Filled** (how many have a value), **Different values**,
  **Smallest** and **Largest** (for text, dates and numbers), **Average** and
  **Total** (numbers). A field with a unit gives its results in that unit.
  There is no median.
- A date is kept at the precision it was written, so grouped by month a
  sample dated only `2019` sits in its own group, **2019, month not known**,
  rather than being guessed into January.
- The last row is the totals over every record listed, each counted once.
- Click a group to list its records: its condition is added to the filter.
- **Download** saves the summary as CSV, Excel, TSV or JSON.
- **Table | Chart** draws the same summary. The first grouping decides the
  chart: dates by period are a line over time, numbers in ranges a histogram,
  anything else bars. Periods and ranges with no records between the first
  and the last are drawn as 0 (or as a gap, for an average). A second
  grouping becomes the series: the five largest are drawn (stacked for
  counts and totals, side by side otherwise) and the table has the rest.
  When several things are shown, pick which one the chart plots. Records
  with no value, and dates less precise than the period, are named under
  the chart with their numbers instead of being placed on the axis. Click a
  bar or a point to list its records, as with a row of the table.

The choices are in the address (`show=summary&sum.by=site.region,taken:month&sum.m=count,mean:depth`),
so a summary can be bookmarked or pinned. Scripts get the same from
`POST /api/records/summary` (the list's selectors plus `group_by` and
`measures`, written the same way; `?format=csv` for a file) and from
`civex record summarise --in <collection> -s <kind> --by <field>[:month|:5]
-m count -m mean:<field> [--csv]`. Which measures and groupings each type
allows is in `GET /api/schemas/field-types`.

### On a map

**Map** appears beside **Summary** when the kind listed, or a kind above it,
has a location field. It shows exactly the records the list shows (the same
level, filters, search and saved filter); when the location belongs to a kind
above ("Samples placed by their Site"), each record is drawn where that
record is. With several location fields, **Place by** picks one.

- Points that crowd together are drawn as one circle with a number. Click it
  to zoom in, or, when they are all at one place, to see their names.
- Lines and areas are drawn as they are.
- Click a record to see its name, a link to its page.
- The map frames the records each time the list changes. It shows the first
  10,000 and says so when there are more.

The base map is the same as the location editor's: coastlines that work
offline, plus street detail when a tile address is set in
**Settings → Map**. Scripts get the points from `POST /api/records/points`
(the list's selectors plus `field`, and `field_schema` for a kind above).
Drawing a box on the map to filter is not possible yet.

## Changing records

```bash
civex record update f623        # asks for each field, current value as default
```

In the app, edit on the record's page. With a file attached, text, number and
date fields have **from filename** to fill them from the file's name.

### Changing many records at once

To set a field to the same value on many records (mark a batch as checked,
fill in the site for a day's uploads), tick them in the explorer, or tick a
whole page and choose **Select all N matching**, then choose **Edit…**. Pick
the field (and **Another field** for more), enter the value with the field's
usual input, or choose **Clear** to empty it. Before you confirm, the dialog
says how many records would change, how many already have the value, which
can't take it and why, and how many workflow runs the change would start.
From the command line:

```bash
civex record set status=checked --id f623 --id a91c            # these records
civex record set status=checked --in survey -s sample -w status=new   # all a list shows
civex record set notes= --in survey -s sample --dry-run         # clear; say what would happen
```

Each value is read as its field's type. A record takes every change or none:
one that can't (a value outside the field's limits, a uniqueness key another
record already uses, a field its kind doesn't have) is left as it is and named,
and the others are changed. Only a kind's own fields are offered: a field it
inherits holds its value on the record above, so edit that kind instead. Files
are added one record at a time. Each record's history shows the change, and
the whole edit is one event in Activity, where **Undo** puts it all back
(see [Undo a mistake](../how-to/undo-mistakes.md#undo-a-bulk-edit)).

### Moving records to another collection

A record can be moved to another collection, or inside another record there.
It keeps its id, its values and its history, and takes everything beneath it
along; its files stay where they are stored. In the app, tick the records in
the explorer and choose **Move to…**; the dialog says how many records would
go, with everything inside them, and whether anything is in the way, before
you confirm. From the command line:

```bash
civex record move f623 a91c --to archive              # to the top of `archive`
civex record move f623 --to archive --under 7b2e      # inside a record there
civex record move f623 --to archive --dry-run         # say what would happen
civex record move-all survey --schema visit --to archive       # every visit in `survey`
```

A move is refused whole, and the dialog or the command says why, when a record
elsewhere references one being moved (a record may only reference its own
collection's records or a global collection's), a uniqueness key is already
taken where the records would land, or the kind of record can't sit where it
would go. The move is one event in Activity, and a record's history reads it
as a change of collection.

## Deleting and undoing

```bash
civex record delete f623        # with its children, to Recently Deleted
civex record restore f623
civex record delete-all survey-2024 --schema sample
```

A record linked from another record's `reference` field can't be deleted without
`--force`, which clears those links.

Every change is in history: a record's **History** tab, a collection's
**Activity** tab, and **Activity** in the sidebar for the whole project. Each
line says who, what and when, and a bulk operation is one line. Any entry on a
record can be reverted:

```bash
civex history record f623
civex history revert <entry id>
```

See [Undo a mistake](../how-to/undo-mistakes.md) and
[Deleting & restoring data](deleting-and-restoring.md).

## Copying a project's data

`civex bundle export` writes schemas, collections, records (their ids kept),
the files they cite and the project's workflows to one file, and `civex bundle
import` reads it into another project; in the app, **Export bundle…** and
**Import bundle…** on the Collections page. It leaves out history and
settings. See [Back up a project](../how-to/back-up.md).
