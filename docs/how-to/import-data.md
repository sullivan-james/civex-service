# Import a spreadsheet or a folder of files

**Goal:** turn an existing CSV, or a folder of recordings, images or documents,
into records without typing them in one by one.

## In the app: guided import

Open a collection and choose **New ▸ Import data…**. (A schema's page has
**Import data** too, for picking the collection as you go.) The import has four
steps:

1. **Source**: **Spreadsheet** (a `.csv` file) or **Files** (any number of files).
2. **Map**: which kind of record to make, and how the data fits it.
3. **Confirm**: what will be created or updated, and anything that will be
   skipped and why.
4. **Done**: what was made, with links to it.

Nothing is written before **Confirm**.

### A spreadsheet

Each row becomes a record. In **Map**, choose the record type, then for each
column choose the field it goes into, **+ Create new field**, or **Skip this
column**. Columns are matched to fields by name to start with.

```text
site,taken_on,depth_ft
North Ridge,2024-03-15,41
South Bay,2024-03-16,131
```

Mapped to a `sample` schema: `site` → *site*, `taken_on` → *taken on*, and
`depth_ft` → *depth*, a field stored in metres, with the column's unit set to
`ft`. The two records get depths of `12.4968` and `39.9288`.

- **Units:** for a field with a unit, say which unit each column is written in,
  and values are converted as they come in. Nothing already stored is converted.
- **Times:** a time without a UTC offset is read in the collection's timezone
  (UTC if it has none). The Map step says which applies. Set the timezone on the
  collection *before* importing.
- **Child records** (a Recording inside an Encounter) need the parent record
  chosen in this step.

### A folder of files

Choose the field each file is stored in (**Store each file in**), then how files
become records:

- **Create one record per file**: every file becomes a new record.
- **Match to existing records by a key in the filename**: for files named after
  records that already exist, such as `sel_03.txt` going to Selection 3. A
  matching record is updated, and a new one is made where no key matches. This is
  available for a record type that sits inside another, once you choose the
  parent.

**Also fill a field from the filename** reads a value out of each name with a
pattern, for example the start time in `20240315_093000.wav`. A preview shows
what each file gives.

On **Confirm**, tick **Save this as a reusable automation** to keep the
import as a workflow, and run it again later from the Workflows page on a new
folder of files.

## From a terminal: a workflow

There is no `civex import` command. A folder import is a short workflow, so it
can be scripted and repeated. Save this as `_civex/workflows/load-recordings.yaml`:

```yaml
name: load-recordings
record_schema: encounter        # run it on an encounter
inputs:
  files:
    type: files
    label: WAV files

steps:
  - id: insert
    plugin: civex.create_records_from_files
    config:
      schema: recording
      file_field: audio
    inputs:
      files: __input__.files
```

Then run it on the encounter the recordings belong to:

```bash
civex workflow run load-recordings --record 2d69dc46 --input "files=recordings/*.wav"
```

Each new recording is created inside that encounter. To read values out of the
file names as well, see [Fill fields from file names](fill-fields-from-filenames.md).
For tables, the [Parse Table](../reference/plugins/parse_table.md) and
[Upsert Records](../reference/plugins/upsert_records.md) plugins do the same for
CSV and TSV files.

## See also

- [Collections & records](../guides/collections-and-records.md): what a collection
  allows, and adding records one at a time.
- [Schemas & fields](../guides/schemas-and-fields.md): units, timezones and partial
  dates, which decide how imported values are read.
