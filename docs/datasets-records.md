# Datasets & Records

## Datasets (collections)

A dataset — called a **collection** at the CLI/UI level — is a named container for records. One project might have a single collection; a multi-site study might have one per site.

```bash
civex collection create study-2024
civex collection create study-2024 --description "Brazil field season 2024"
civex collection list
civex collection show study-2024
civex collection delete study-2024   # also deletes all records inside
```

There is no schema constraint on a collection — a single collection can hold records of different schemas.

## Adding records

```bash
civex record add --to <collection> --schema <schema>
```

The CLI prompts for each field on the schema in order. Required fields must be filled; optional fields can be left blank.

For `file` fields, enter the path to the file on disk. Civex stores a copy in its content-addressed object store and saves a reference (filename + SHA-256) in the record.

For `reference` fields, enter the target record's ID or any unique prefix of it.

For schemas with a parent, civex first prompts for the parent record ID.

## Viewing records

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

Every record has a UUID. You can refer to any record by its full UUID or by any unique prefix — civex errors if the prefix is ambiguous.

## Updating records

```bash
civex record update <record-id>
```

The CLI prompts for each field again, showing the current value as the default. Press Enter to keep the existing value.

## Deleting records

```bash
civex record delete <record-id>

# Delete every record in a collection (optionally filtered by schema)
civex record delete-all study-2024 --schema trial
```

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
