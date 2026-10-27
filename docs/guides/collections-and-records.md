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
    and gives you a blank form. **New ▸ Import data…** brings in a spreadsheet or
    a folder of files: see [Import data](../how-to/import-data.md).

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
- **Search** is scoped to where you are.
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
  [Files](files.md#working-on-many-files-their-files).
- Tick rows (shift-click for a range) to **Delete** or **Run workflow on N**.
  Ticking a whole page offers **Select all N matching**.

Everything is in the address, so a filtered list can be bookmarked and Back
undoes a step. Scripts get the same from `GET /api/records` with `schema`,
`within`, `filter`, `sort` and `search`.

A record's **Referenced by** section counts the records linking to it, per
collection, schema and field (`GET /api/records/{id}/referrers`).

## Changing records

```bash
civex record update f623        # asks for each field, current value as default
```

In the app, edit on the record's page. With a file attached, text, number and
date fields have **from filename** to fill them from the file's name.

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
