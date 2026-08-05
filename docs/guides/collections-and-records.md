# Collections & records

## Collections

A **collection** is a named container for records. One project might have a single collection; a multi-site study might have one per site. There is no schema constraint on a collection — a single collection can hold records of different schemas.

=== "CLI"
    ```bash
    civex collection create study-2024
    civex collection create study-2024 --description "Brazil field season 2024"
    civex collection list
    civex collection show study-2024
    civex collection delete study-2024   # also deletes all records inside
    ```

=== "Web UI"
    Go to **Collections → New collection**. On a collection's detail page, **Delete collection** removes it and every record inside.

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
    A collection's detail page lists its records, with a schema filter and a free-text search box (matches anywhere in the record's field values, not per-field like `--where`).

Every record has a UUID. You can refer to any record by its full UUID or by any unique prefix — civex errors if the prefix is ambiguous.

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

    # Delete every record in a collection (optionally filtered by schema)
    civex record delete-all study-2024 --schema trial
    ```

=== "Web UI"
    Select one or more rows in a collection's record list and click **Delete**, or use **Delete all** (scoped to the current schema filter) on the collection's detail page.

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
