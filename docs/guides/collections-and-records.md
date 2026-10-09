# Collections & records

A **collection** holds records: one per study, site or season, as suits you. It
says which [schemas](schemas-and-fields.md) its records may be, and who may
link to them.

## Collections

```bash
civex collection create humpbacks --schema encounter --schema recording \
  --description "2024 field season" --timezone America/Chicago
civex collection show humpbacks
```

```text
humpbacks
  Records  0
  2024 field season
  Timezone  America/Chicago
  Scope     local
  Schemas   encounter, recording
```

| Setting | Means |
|---|---|
| **Schemas** (`--schema`, `add-schema`) | Records here can only be of these. A new collection with none holds nothing. A child schema needs its parent listed too (`add-schema` adds parents for you). A schema with records here can't be removed |
| **Scope** (`--scope`) | `local` (default): only records here can link to these. `global`: any collection can, for shared lists such as species, sites or people |
| **Timezone** (`--timezone`) | How times without a UTC offset are read and shown. See [Times and timezones](schemas-and-fields.md#times-and-timezones) |

```bash
civex collection add-schema humpbacks selection
civex collection create taxonomy --scope global --schema species
civex collection list
```

A `reference` field links to records in its own collection or in a global one,
never in another local collection. A global collection that others link to can't
be made local or deleted.

**In the app:** **Collections → New collection**, and **Edit** on a collection's
page.

## Adding records

=== "Web UI"
    In a collection, the **New** menu lists the kinds you can add here. Inside a
    record, it lists the kinds that go inside it. **Add and add another** saves
    and gives you a blank form. **New ▸ Import data…** brings in a spreadsheet or
    a folder of files: see [Import data](../how-to/import-data.md).

=== "CLI"
    ```bash
    civex record add --to study-2024 --schema trial
    ```

    ```text
      subject (string) [required]: S01
      duration (float) []: 12.5
      result (string) []: pass
      summary (string) []:
    Added record f623c8d7-eb75-41e1-b2ec-d6feb7f02f7a.
    ```

    For a child schema it asks for the parent record first. A file field takes a
    path, and a reference takes a record id or any unique prefix of one.

## Finding records

```bash
civex record find --in study-2024 --schema trial --where "result=pass" --limit 20
civex record show f623
```

```text
Record f623c8d7-eb75-41e1-b2ec-d6feb7f02f7a
  Schema    trial
  Created   2026-10-09 11:11 UTC
Field     Value
subject   S01
duration  12.5
result    pass
summary   pass
```

`--where` repeats, and all conditions must match. Every record has a UUID, and
any unique prefix of it works wherever an id is asked for.

### The explorer

A collection's page (and a record's **Contains** tab) is one explorer:

- **Levels:** the collection's schemas top-down (Encounter → Recording →
  Selection), with counts. A row shows its children ("3 recordings →"). Click to
  go down, and use the trail to go back up.
- **Search** is scoped to where you are.
- **+ Filter** builds AND/OR conditions on this level's fields, a parent's, or
  any child's: "Recordings that have a Selection whose `quality` is empty" is
  one condition. Reference values are picked by name.
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

## Deleting and undoing

```bash
civex record delete f623        # with its children, to Recently Deleted
civex record restore f623
civex record delete-all study-2024 --schema trial
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

`civex dump` writes schemas, collections, records and workflows to one YAML
file, and `civex restore` reads it into another project. It leaves out files,
history and settings. See [Back up a project](../how-to/back-up.md).
