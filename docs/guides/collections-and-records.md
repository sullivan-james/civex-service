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

A collection's page is its records, in one explorer. A record's page says
what kind of thing it is above its name, shows its fields (the first few,
with **Show all**, when it has records inside it) and then what it
**Contains**: a chip for each kind inside with its count, a search, and the
rows, each a link to that record. It is the same explorer with some of it
folded: **Filter** beside the search opens the filters, saved filters,
columns and export, and **Charts** opens the charts. Rows are ticked there
as anywhere, to edit, run a workflow on, move or delete. Files, Exports, Activity and
the collection's details are in the **⋯** menu at the top of the page.

The explorer has three ideas. **Records** are the rows: each row is one
record. **Filters** say which rows you see. **Charts** count the rows you see.


- **Levels:** the collection's schemas top-down (Site → Visit → Sample),
  with counts. A row shows its children ("3 visits →"). Click to go down, and
  use the trail to go back up.
- **All kinds**, the first of the levels, lists every kind of record at once
  (in the collection, in every collection on **All records**, or inside the
  record you are in), with its name, kind, collection and when it was last
  edited. It can be searched, filtered by open notes, sorted by those columns,
  moved and deleted; filtering by a field, charts, **Edit…** and **Run
  workflow** need one kind, so pick one first.
- **Search** is scoped to where you are. It looks, ignoring case, in what the
  records hold: text, numbers, the items of a list (tags, choices) and the
  names of files. It never matches a file's hash, a reference or a location,
  so a short search like `a3` finds only records that show `a3`. Typing the
  start of a record's id (four characters or more) finds that record too.
  A link or script can narrow it to one field (`qin` in the address,
  `search_field` on the API).
- **+ Filter** builds AND/OR conditions on this level's fields, a parent's, or
  any child's: "Visits that have a Sample whose `depth` is empty" is one
  condition. Reference values are picked by name.
- **Saved filters** keep a filter to come back to: see
  [Saved filters](views.md). **Save this filter** saves yours, and everyone
  sees it.
- **Columns**, beside the count of records, include parents' fields and
  fields through a reference. Your choice for a kind is remembered in this
  browser. Click a header to sort.
- **Export** takes exactly the rows listed or ticked. See
  [Get files out](../how-to/export-files.md). It also offers the charts on
  screen, one or all of them, as tables of their numbers.
- The files of what's listed (to move between drives, download or free up)
  are under **Files** in the page's **⋯** menu. See
  [Files](files.md#working-on-many-files).
- **Charts** sit beside the records and count exactly what is listed: see
  [Charts](#charts).
- Under the table, a last row gives, for every record listed (not just the
  page), the average, smallest and largest of each number column and how many
  different values each choice column holds.
- A count such as **3 problems** beside the number of records appears only
  when something needs a look: see [Checking the data](#checking-the-data).
- Tick rows (shift-click for a range) to **Delete** or **Run workflow on N**.
  Ticking a whole page offers **Select all N matching**.

Everything is in the address, so a filtered list can be bookmarked and Back
undoes a step. Scripts get the same from `GET /api/records` with `schema`,
`within`, `filter`, `sort`, `search` and `search_field` (repeatable: the fields
to search in), and from `civex record find --in <collection> --schema <kind>
--search <text> [--search-field <field>]`.

A record's **Referenced by** section counts the records linking to it, per
collection, schema and field (`GET /api/records/{id}/referrers`).

### Charts

Charts are a panel beside the records. Like the navigation on the left, it
folds away with the button at its top and opens again from the **Charts**
button it leaves; another button shows the charts at full width, with **Back to
records**. Drag the line between the records and the charts to make the panel
wider (the cards then sit in two columns). These choices are remembered in
this browser. Every chart counts
exactly the records listed: the same kind, place, search and filters. There
are no charts until someone adds one.

- **Click a bar** (or a point, or a slice) to filter by its value. The table
  and the other charts follow, a chip appears above, and clicking it again
  takes it out. **Clear filters** beside the chips removes them all.
  Several bars of one chart are "is any of". The chart you clicked keeps all
  its bars, with the chosen ones lit, so you can pick another.
- A filter made from bars is the ordinary filter: it can be changed with
  **+ Filter**, saved with **Save this filter**, and shared as a link. When a
  filter uses a chart's field in a way bars can't show (inside an "or" with
  another field, or "is not"), the chart counts the filtered records with
  nothing lit.
- **Which charts.** A kind of record says which charts its lists open with
  (also on its **Charts** tab on the schema page). A kind starts with none.
- **Add chart** opens the builder at full width: the choices on the left and
  the chart they make on the right, drawn live. First **What**: what to
  **Show** (how many records, or the average, total, smallest or largest of
  a number, how many have a field filled in, or how many records of a kind
  beneath are inside them) **For each** value of a field (a date by year,
  month, week or day; a number in steps you choose; a location places the
  records). Then **How** it is drawn, from the ways that fit: **Bars**,
  **Line** (over dates or steps), **Pie** (of counts and totals), **Table**,
  or **Map** (for a location). **Quick picks** fill the choices in for the
  kind's fields of choices and its first date. Give it a title of your own
  if you like, then **Add chart**.
- Drag a chart by its title to move it. Its **⋮** menu has **Edit…** (the
  builder again, on that chart, where you can also give it a title of your
  own), **Larger** / **Smaller**, **See numbers** (the chart above the
  records with its table of numbers and **Download numbers**: CSV, Excel,
  TSV, JSON; it is in the address, so it is a link and Back closes it),
  **Move up** / **Move down** and **Remove**. Every change is saved for the
  kind at once, for everyone, like a saved filter (it takes the right to
  write records).
- **Add to Analytics page**, in a chart's menu, puts it on the
  [Analytics page](views.md#the-analytics-page) with the records it counts now.
- A very large list (over 200,000 records) waits for **Show charts**.

How values are grouped: a date is kept at the precision it was written, so by
month a sample dated only `2019` is its own bar, **2019, month not known**. A
date and time is grouped in its field's time zone, else the collection's,
else UTC. A list (tags, links) puts a record in a bar for each item. There is
no median.

A **map** chart shows the listed records by a location field of their kind or
of a kind above it (each record is drawn where that record is). Points that
crowd together are one circle with a number; click a record for its name and
a link to its page. Opened large it is the full map, and with several
location fields one can be picked. It shows the first 10,000 and says so.
The base map is the location editor's: coastlines that work offline, plus
street detail when a tile address is set in **Settings → Map**. Narrowing the
records by drawing an area is not possible yet.

Scripts get the same numbers from `POST /api/records/summary` (the list's
selectors plus `group_by` and `measures`, e.g. `site`, `taken:month`,
`depth:5`; `count`, `mean:depth`, `inside:reading`; `?format=csv` for a file)
and from `civex record summarise --in <collection> -s <kind> --by
<field>[:month|:5] -m count -m mean:<field> [--csv]`; a map's points from
`POST /api/records/points`. Which of these each field type allows is in
`GET /api/schemas/field-types`.

### Checking the data

Beside the number of records, a count such as **3 problems** appears when
something in exactly the records listed (the same level, filters and search)
needs a look. Nothing is shown when all is well. Click it for the list, counted
per field; **Back to records** returns. For a list of more than 5,000 records
the count is not worked out by itself, since that reads every record: open
`?show=checks` or use the command below.

- **Breaks a rule**: a value its field's rules refuse now. Rules are checked
  when a value is saved, so tightening one later (a lower maximum, fewer
  choices, a finer date precision) leaves the values already stored as they
  were. Such a record can still be edited (a save checks only the values it
  changes), and its broken values can be put right one at a time, by hand or
  with a bulk edit.
- **Required but empty**: a field marked required with no value.
- **Shares a unique key**: records in one place with the same values for
  fields that should be unique together.
- **Broken link**: a link to a record that was deleted, or that the record can
  no longer reach.
- **Missing file**: a file that is on no drive here and not on the server.

Each line gives the count and a few of the records. Click it to list them all:
open one, or tick them and choose **Edit…** to put them right in one go (see
[Changing many records at once](#changing-many-records-at-once)). A required
field left empty has **Show in the list**, which adds the condition to the
explorer's filter. Unusual numbers are not looked for.

From the command line, with the same options as `record find`:

```bash
civex record check --in survey -s sample                       # one line per field and issue
civex record check --in survey --issue breaks_rule --field depth   # the records, with their ids
```

Scripts use `POST /api/records/quality` (the list's selectors) and
`POST /api/records/quality/records` (`issue`, `field`, `kind`, `limit`,
`offset`).

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

## Notes on records

A note is a short text about a record, "value looks off, re-check the
calibration". The record's **Notes** tab lists its notes as threads: each note
with the replies to it underneath, oldest first, with who wrote them and when.
Anyone who may change records in the collection can add a note, **Reply** in a
thread, **Resolve** a thread once it is dealt with (or **Reopen** it), and
delete a note or a reply; only its author can change its words. Replying to a
resolved thread opens it again. Deleting the note that starts a thread hides
its replies too, and restoring it brings them back.

The record's header says how many threads are still open, and links to its
Notes tab. Beside the number of records, any list says **N open notes** when some of
the records listed have one; click it to list them. **All open notes** on a
record's Notes tab lists every record with an open
thread, of every kind, in every collection: it is the **All records** tab of
Collections with **All kinds** picked, filtered with **Has open notes**, so
search and the Open notes filter work on it, and a record opens on its Notes
tab. Pick a kind to filter by its fields too. **Open notes inside** on a
record's Notes tab lists the same for everything inside that record. The **Open notes** column
(**Columns › Open notes**) shows how many threads are open and the first line
of the latest, in any list.

```bash
civex record note add f623 "depth looks off, re-check the calibration"
civex record note reply 3c1d "it was the sensor, swapped on the 3rd"
civex record note list f623 --open
civex record note resolve 3c1d
```

Notes are in history and sync to the other computers following the project;
two people replying at once are just two replies. Deleting a record hides its
notes until it is restored; deleting it permanently removes them, history and
all. Scripts use `/api/records/{id}/notes` and `/api/notes/{id}/replies`.

### Signing off records

To mark records as checked, or to track a QC state ("pending", "passed",
"failed"), add a field for it: a **Choice** field such as `qc` with those
choices, or a **Yes / no** field `checked`. Set it on many records at once with
**Edit…** on the explorer's selection bar (bulk edit), and find what is waiting
with the explorer's filter (**qc is pending**). Being a field, it is in each
record's history, syncs, exports, and can start a workflow.

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
import` reads it into another project; in the app, **Copy to another project…** and
**Bring in from another project…** on the Collections page. It leaves out history and
settings. See [Back up a project](../how-to/back-up.md).
