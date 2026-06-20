# Datasets & Records

## Datasets

A dataset is a named container for records. One project might have a single dataset; a multi-site study might have one per site.

```bash
civex dataset create study-2024
civex dataset create study-2024 --description "Brazil field season 2024"
civex dataset list
civex dataset show study-2024
```

There is no schema constraint on a dataset — a single dataset can hold records of different schemas.

## Adding records

```bash
civex record add --to <dataset> --schema <schema>
```

The CLI prompts for each field on the schema in order. Required fields must be filled; optional fields can be left blank.

For `file` fields, enter the path to the file on disk. Civex stores a copy in its content-addressed object store and saves a reference (filename + SHA-256) in the record.

For `reference` fields, enter the target record's ID or any unique prefix of it.

For schemas with a parent, civex first prompts for the parent record ID.

## Viewing records

```bash
# Show one record by ID (short prefix is fine)
civex record show abc123

# List records in a dataset
civex record find --in study-2024

# Filter by schema
civex record find --in study-2024 --schema selection

# Filter by field value
civex record find --in study-2024 --schema trial --filter "outcome=pass"

# Paginate
civex record find --in study-2024 --limit 20 --offset 40
```

## Updating records

```bash
civex record update <record-id>
```

The CLI prompts for each field again, showing the current value as the default. Press Enter to keep the existing value.

## Deleting records

```bash
civex record delete <record-id>
```

## Exporting and restoring

Export everything (schemas, datasets, records, workflows) to a single YAML file:

```bash
civex dump --output backup.yaml

# Schemas and workflows only — no record data
civex dump --no-data --output schema-only.yaml

# Restore on another machine
civex restore backup.yaml
```

File attachments referenced by records are not included in the dump file. Export the `.civex/objects/` directory separately if you need to preserve files.
