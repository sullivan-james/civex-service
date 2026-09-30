# Collections & records

## Collections

A **collection** is a named container for records. One project might have a single collection; a multi-site study might have one per site. There is no schema constraint on a collection — a single collection can hold records of different schemas.

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
    Go to **Collections → New collection**. On a collection's detail page, **Delete collection** moves it and every record inside to Recently Deleted — see [Deleting & restoring data](deleting-and-restoring.md).

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
- **Filters** — click **+ Filter** to add conditions on this level's fields, on a *parent* record's fields, or on *any child* record's fields. "Recordings that have a selection whose `selection_table` is empty" is one condition; drill into a recording and the filter still applies, now to its selections. Conditions are AND/OR groups, like a view's.
- **Saved filters** — the chips are the current schema's [views](views.md): click one to apply it. Save your own with **Save as view…**. They belong to the schema, so everyone sees them.
- **Columns, sort and export** — choose columns (including inherited fields and one-hop reference joins), click a header to sort, and **Export** downloads exactly the rows listed.

Everything you choose is in the page's URL, so a filtered list can be bookmarked or shared, and Back undoes a drill-down.

The same selection is available to scripts: the records API takes `schema`, `within` (a record — list only its descendants), `filter`, `sort` and `search`, and a filter condition may name another `schema` (see the [HTTP API reference](../reference/http-api.md)).

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

## Exporting and restoring

Export everything (schemas, collections, records, workflows) to a single YAML file:

```bash
civex dump --output backup.yaml

# Schemas and workflows only — no record data
civex dump --no-data --output schema-only.yaml

# Restore on another machine
civex restore backup.yaml
```

File attachments referenced by records are not included in the dump file. Export the `_civex/objects/` directory separately, or use [remote sync](remote-sync.md), which transfers objects automatically.

For a quick, human-readable export of a single collection instead of a full backup, use **Export CSV** on the collection's detail page in the web UI.
