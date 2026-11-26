# Import data

## A spreadsheet

**Goal:** bring a CSV or Excel file into a collection as records.

Open the collection, choose **New**, then **Import spreadsheet**.

1. Choose the file. It is sent as it is and read on the server, a part at a time,
   so a large file is fine.
2. Say where each column goes: into a field the kind of record already has, into a
   new field (its type is guessed from the first rows, and you can change it), or
   nowhere. For a new kind of record, every heading becomes a field. To update
   records already there when you import again, choose the column that identifies
   a record, and whether a match is updated or left alone.
3. Check: nothing is saved yet, but you see how many records would be added,
   changed or not saved, and why each row that won't work won't (a value that isn't
   a number in a number field, a date that isn't a date, a key repeated).
4. Import. It reports its progress, and the whole import is one event in
   History, so the records it brought in can be undone from there.

Values are read as written: `007` stays `007`, and a column is only taken for
numbers or dates when every value in the first rows is one. Records that belong
inside another record are not imported this way.

The wizard runs the Table and Save as records steps, so the same import can be
scripted as a workflow, as below.

## A folder of files

**Goal:** turn a folder of readings, images or documents into records without
adding them one by one.

A folder import is a short workflow, so it can be scripted and run again on the
next folder: a workflow saved once is run from a record's page or the Workflows
page.

Save this as `_civex/workflows/load-samples.yaml`:

```yaml
name: load-samples
record_schema: visit            # run it on a visit
steps:
  - id: readings
    plugin: civex.files@1
    config:
      source: run              # chosen when it is run
      label: CSV files

  - id: insert
    plugin: civex.save_records@1
    config:
      schema: sample
      if_exists: add_new       # a record for every file
      file_field: reading
    inputs:
      files: readings.files
```

Then run it on the visit the samples belong to:

```bash
civex workflow run load-samples --record 2d69dc46 --input "readings=readings/*.csv"
```

Each new sample is created inside that visit. To read values out of the
file names as well, see [Fill fields from file names](fill-fields-from-filenames.md).
For tables, the [Table](../reference/plugins/table.md) and
[Save as records](../reference/plugins/save_records.md) steps do the same for
CSV, TSV and Excel files; with **Match on** (or a unique key on the kind of record) a
row updates the record already there, so importing the same table again changes
nothing.

On your own computer, a **Files** step can read a whole folder instead
(`source: folder`, or choose a folder in the run dialog): the files are read from
disk where they are, nothing is uploaded, and files already stored are skipped, so
it is much faster for many files.

## See also

- [Collections & records](../guides/collections-and-records.md): adding records
  one at a time.
- [Schemas & fields](../guides/schemas-and-fields.md): units, timezones and partial
  dates, which decide how imported values are read.
