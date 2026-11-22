# Import a folder of files

**Goal:** turn a folder of readings, images or documents into records without
adding them one by one.

A folder import is a short workflow, so it can be scripted and run again on the
next folder. There is no import wizard in the app: a workflow saved once is run
from a record's page or the Workflows page.

Save this as `_civex/workflows/load-samples.yaml`:

```yaml
name: load-samples
record_schema: visit            # run it on a visit
inputs:
  files:
    type: files
    label: CSV files

steps:
  - id: insert
    plugin: civex.create_records_from_files
    config:
      schema: sample
      file_field: reading
    inputs:
      files: __input__.files
```

Then run it on the visit the samples belong to:

```bash
civex workflow run load-samples --record 2d69dc46 --input "files=readings/*.csv"
```

Each new sample is created inside that visit. To read values out of the
file names as well, see [Fill fields from file names](fill-fields-from-filenames.md).
For tables, the [Read a table from a file](../reference/plugins/parse_table.md) and
[Make a record for each row](../reference/plugins/rows_to_records.md) plugins do the same for
CSV and TSV files; with **Match rows by** (or a unique key on the kind of record) a
row updates the record already there, so importing the same table again changes
nothing.

## See also

- [Collections & records](../guides/collections-and-records.md): adding records
  one at a time.
- [Schemas & fields](../guides/schemas-and-fields.md): units, timezones and partial
  dates, which decide how imported values are read.
