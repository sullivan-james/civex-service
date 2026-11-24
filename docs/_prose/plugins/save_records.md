# `civex.save_records@1`  (Save as records)

Save the **rows of a table** or a set of **files** as records, one record for each
row or file. When a matching record already exists, **If a matching record already
exists** (`if_exists`) says what happens:

| `if_exists` | A row or file whose record is there | One whose record is not |
|---|---|---|
| `update` (default) | changes the record, only what the table or file brings | makes a record |
| `skip` | leaves the record as it is (counted in `skipped`, named in `skipped_rows`) | makes a record |
| `add_new` | never looks for a match: always makes another record | makes a record |

Running the same table or files again changes nothing: the records are matched, found
unchanged (`unchanged`), left without history and without starting any workflow.

Give it either `rows` (from **Table**) or `files` (from **Files**), not both.

<!-- civex:tables -->

## Tables

```yaml
- id: sheet
  plugin: civex.table@1
  config:
    field: sample_sheet

- id: save
  plugin: civex.save_records@1
  config:
    schema: Sample
    dataset: survey-2024
    match_on: [number]
    field_mapping:
      "Taken at": taken_at
      "Depth (m)": depth
      "Sample": number
  inputs:
    rows: sheet.table
```

### How a row finds its record

**Match on** (`match_on`) names the fields a row and a record must agree on to be
the same record. They are the kind's own fields, named after **Columns to fields**
(`field_mapping`) is applied (`number` above, not the column `Sample`). A row is
matched only against records of that kind inside the same record (**Inside
record**, else the record the workflow runs on), in the collection it writes to.

- Left empty, the kind's first **unique key** is used (the run log says so).
- Left empty on a kind with no unique key, every row makes a new record.

Values are compared the way a unique key compares them: a number by its value (`12`
and `12.0` are the same; a column with a blank cell reaches the step as decimals), so
a table re-read from the same file always finds its records. A number given for a
text field is written and matched as its text (`"12"`).

### What an update keeps

An update changes **only the columns in the table**. Every other field on the matched
record (a file, values computed by another workflow) is left exactly as it is, and an
empty cell leaves its field alone instead of clearing it.

### Rows it leaves out

A row is skipped, counted in `skipped` and named in `skipped_rows` (the run shows them
as problems), when:

- a field it is matched by is empty in that row;
- its key repeats an earlier row of the same table (the first is saved; the step never
  guesses which of two rows is right);
- several records already have its key;
- `if_exists` is `skip` and its record is there;
- the record refuses its values (a restriction, a required field, a unique key).

The other rows are saved.

## Files

```yaml
- id: wavs
  plugin: civex.files@1
  config:
    source: run
    label: Sequence WAV files

- id: put
  plugin: civex.save_records@1
  config:
    schema: sequence_selection
    if_exists: update
    match_on: [selection_number]       # compared with the key in the file name
    filename_pattern: 'sel_(\d+)'      # one capture group: the key
    file_field: seq_wav_file           # where the file goes
  inputs:
    files: wavs.files
```

**The key in each file's name** (`filename_pattern`) is a regular expression with one
capture group; the captured text is compared with the one **Match on** field (`01` and
`1` are the same number). **Put the file in field** (`file_field`) is a file or file-list
field: a file-list field gets the file added (once; the same content is never added
twice), a file field holds the file itself. A file whose key matches no record makes
one, with the key in the match field.

- With `add_new`, no key is needed: every file makes a record (the pattern, if given,
  still fills the match field).
- Two files in one run with the same key are **not** attached (one record holds one
  file): they are listed in `ambiguous`, and nothing wrong is written. That is almost
  always a pattern that reads too little of the name (`sel_(\d{2})` takes `14` from both
  selection 14 and 149).
- A file whose name has no key is listed in `unmatched`, with files whose record could
  not be saved.
