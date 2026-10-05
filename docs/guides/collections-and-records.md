# Collections & records

## Collections

A **collection** is a named container for records. One project might have a single collection; a multi-site study might have one per site. A collection is *for* a set of schemas you choose (see [Schemas and scope](#schemas-and-scope)) and can hold records of any of them.

=== "CLI"
    ```bash
    civex collection create study-2024
    civex collection create study-2024 --description "Brazil field season 2024"
    civex collection list
    civex collection show study-2024
    civex collection delete study-2024   # moves it + every record inside to Recently Deleted
    civex collection restore study-2024  # undoes it
    ```

=== "Web UI"
    Go to **Collections → New collection**, then choose its scope and schemas. On a collection's detail page, **Delete collection** moves it and every record inside to Recently Deleted — see [Deleting & restoring data](deleting-and-restoring.md).

## Schemas and scope

Each collection has two settings beyond its name.

**Schemas** — the schemas the collection is for. Records in it can only be of these, so a new collection holds nothing until you enable at least one. A child schema needs its parent schema enabled too (a child record's parent lives in the same collection). A schema that still has records in a collection can't be removed from it.

**Scope** — who may reference the collection's records:

- `local` (the default): only records in the same collection.
- `global`: records in any collection. Use it for shared reference data — species, sites, people — that many studies point at.

A `reference` field can therefore point at a record in its own collection or in a global one, never in another local collection. Reference pickers only search what the record being edited may reference, and a reference to a record from another collection is marked with that collection's name. A global collection that other collections reference can't be made local or deleted.

=== "CLI"
    ```bash
    civex collection create taxonomy --scope global --schema species
    civex collection create study-2024 --schema deployment --schema detection
    civex collection add-schema study-2024 observation   # also enables its parent schemas
    civex collection update study-2024 --scope local
    ```

=== "Web UI"
    Pick the scope and tick the schemas on the **New collection** form, or later from **Edit** on the collection's page.

## Adding records

=== "CLI"
    ```bash
    civex record add --to <collection> --schema <schema>
    ```

    The CLI prompts for each field on the schema in order. Required fields must be filled; optional fields can be left blank.

=== "Web UI"
    On a collection's detail page, click **Add record**, pick a schema, and fill in the form.

For `file` fields, enter the path to the file on disk (CLI) or use the file picker (web UI). Civex stores a copy in its content-addressed object store and saves a reference (filename + SHA-256) in the record — see [Files](files.md).

For `reference` fields, enter the target record's ID or any unique prefix of it (CLI), or pick from the searchable dropdown (web UI).

For schemas with a parent, civex first prompts for the parent record.

## Viewing and filtering records

=== "CLI"
    ```bash
    # Show one record by ID (short prefix is fine)
    civex record show abc123

    # List records in a collection
    civex record find --in study-2024

    # Filter by schema
    civex record find --in study-2024 --schema selection

    # Filter by field value
    civex record find --in study-2024 --schema trial --where "outcome=pass"

    # Multiple conditions (all must match)
    civex record find --in study-2024 --where "outcome=pass" --where "location=Brazil"

    # Limit results
    civex record find --in study-2024 --limit 20
    ```

    `--where` is repeatable — all conditions must match:

    ```bash
    civex record find --in study-2024 --schema trial --where "outcome=pass" --where "location=Brazil" --limit 20
    ```

=== "Web UI"
    A collection's detail page is a record explorer — see [Browsing a collection](#browsing-a-collection) below.

Every record has a UUID. You can refer to any record by its full UUID or by any unique prefix — civex errors if the prefix is ambiguous.

## Browsing a collection

The web UI's collection page (and the **Contains** section of a record's page) is one explorer, built around the schema hierarchy:

- **Hierarchy rail** — the collection's schemas from the top down (for example Encounter → Recording → Selection), each with how many records are in scope. Pick one to list its records. It opens on the top level, not on a mixed list of everything.
- **Drilling down** — a row shows how many children it has ("3 recordings →"). Click it to list them in the same table, scoped to that record. Drill again and you are looking at that record's grandchildren. The trail above the table takes you back up, and so does the rail. On a record's own page the same explorer lists *everything* under that record, at any depth.
- **Search** — always available, and scoped to wherever you are.
- **Filters** — click **+ Filter** to add conditions on this level's fields, on a *parent* record's fields, or on *any child* record's fields. "Recordings that have a selection whose `selection_table` is empty" is one condition; drill into a recording and the filter still applies, now to its selections. Conditions are AND/OR groups, like a view's. On a `reference` or `reference_list` field the value is picked by name from a searchable list, not typed as an ID; a reference list is matched with **includes** (does the list contain this record).
- **Saved filters** — the chips are the current schema's [views](views.md): click one to apply it. Save your own with **Save as view…**. They belong to the schema, so everyone sees them.
- **Columns, sort and export** — choose columns (including inherited fields and one-hop reference joins), click a header to sort, and **Export** downloads exactly the rows listed.

Everything you choose is in the page's URL, so a filtered list can be bookmarked or shared, and Back undoes a drill-down.

The same selection is available to scripts: the records API takes `schema`, `within` (a record — list only its descendants), `filter`, `sort` and `search`, and a filter condition may name another `schema` (see the [HTTP API reference](../reference/http-api.md)).

### What references a record

A record's page has a **Referenced by** section (collapsed until you open it) counting the records that point at it through a `reference` or `reference_list` field, per collection, schema and field. **View all** opens that collection's page filtered to those records. Referrers can sit in another collection when the record lives in a [global collection](#schemas-and-scope). Scripts get the same counts from `GET /records/{id}/referrers`.

## Updating records

=== "CLI"
    ```bash
    civex record update <record-id>
    ```

    The CLI prompts for each field again, showing the current value as the default. Press Enter to keep the existing value.

=== "Web UI"
    Open the record's detail page, edit the form, and click **Save**.

## Deleting records

=== "CLI"
    ```bash
    civex record delete <record-id>
    civex record restore <record-id>     # undo, within the retention window

    # Delete every record in a collection (optionally filtered by schema)
    civex record delete-all study-2024 --schema trial
    ```

=== "Web UI"
    Tick rows in the explorer and click **Delete**. Ticking a whole page offers **Select all N matching**, which deletes every record the current search and filters match — not just the ones on screen — and the confirmation shows the real count.

Deleting a record moves it (and its children, if any) to **Recently Deleted** rather than removing it outright — see [Deleting & restoring data](deleting-and-restoring.md).

## History and undo

Every change to a record, schema, field, collection or view is kept. A record's **History** tab, a schema's **History** tab and a collection's **Activity** tab list the entries newest first; a row shows the first few things that changed (`Count 1 → 2`) and opens to show all of them. A delete lists the values the record held, so you can see what was lost.

**Activity** in the sidebar lists every change in the project, newest first. Each line starts with **Who** made it (the operating-system user on the machine that made the change; a dash for changes from before that was recorded), then what happened, then when. An import, a delete that took a whole tree with it, or a workflow run is **one line** that says what it did ("Deleted 1,204 records"), and opens to the changes inside it. A change to a record that is not there now says so (**Deleted now**, or **Gone for good** once it has been permanently deleted), which is usually what explains something missing. Each change names what it is about, with its short ID, and links to it when it can be opened.

Press **Deleted** to see only what you can still restore. A deleted item has **Restore** on its row, and **Restore all N** restores everything the list shows, after saying what comes back. There is no separate Recently Deleted page.

Changes are filtered the way records and runs are: type in the search box to find a value or a file name, and click **Filter** to build conditions. You can filter by when, what kind of thing, what was done, how (on its own, an import, a delete, a restore, a workflow run), which collection, which schema (the schema's own changes, its fields, and records of that type), which record it is under, and where it is now. The filter is held in the address, so a view can be linked.

The same list is on a record's **History** tab, where it covers the record **and everything beneath it** (so an encounter's history shows a recording that was deleted from it), and on a collection's **Activity** tab, which covers the records in it, deleted ones included.

An entry on a record can be undone. An **update** puts the fields it changed back to the values they had before, a **delete** restores the record, and a **create** deletes it (to Recently Deleted). A field that was edited again after the entry is left alone unless you choose to overwrite it, and a field that no longer exists, or a file that has since been cleaned up, can't be put back and is skipped with the reason. The undo is recorded as an ordinary edit, so it can be undone too. Changes to schemas, fields and collections can be read but not undone, because undoing them could destroy data.

=== "CLI"
    ```bash
    civex history record <record-id>          # also: history schema <name>, history collection <name>
    civex history show <entry-id>             # one entry with every change in full
    civex history revert <entry-id>           # shows what goes back, then asks
    civex history revert <entry-id> --field legs --force
    ```

    Entry ids are the short ones the list prints.

=== "Web UI"
    Open a record's **History** tab, click an entry, then **Revert…**. The next step shows each field as it is now and as it would become, marks any that were edited since, and does nothing until you confirm.

## Exporting and restoring

Export everything (schemas, collections, records, workflows) to a single YAML file:

```bash
civex dump --output backup.yaml

# Schemas and workflows only — no record data
civex dump --no-data --output schema-only.yaml

# Restore on another machine
civex restore backup.yaml
```

File attachments referenced by records are not included in the dump file. Export the `_civex/objects/` directory separately.

For a quick, human-readable export of a single collection instead of a full backup, use **Export CSV** on the collection's detail page in the web UI.
