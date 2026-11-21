# `civex.rows_to_records`

Save each table row as a record. When rows can be matched to the records already
there, a row updates its record instead of making another, so running a workflow
again on the same table (or on a sheet that grew since) changes only what changed.

> Uses pandas, which ships with civex — see `civex.parse_table`.

<!-- civex:tables -->

```yaml
- id: parse
  plugin: civex.parse_table
  inputs:
    bytes: load.bytes

- id: save
  plugin: civex.rows_to_records
  config:
    schema: Sample
    dataset: survey-2024
    match_on: [number]
    field_mapping:
      "Taken at": taken_at
      "Depth (m)": depth
      "Sample": number
  inputs:
    table: parse.table
```

## How a row finds its record

**Match rows by** (`match_on`) names the fields a row and a record must agree on
to be the same record. They are the kind's own fields, named after **Columns to
fields** is applied (`number` above, not the column `Sample`). A row is matched
only against records of that kind inside the same record (**Inside record**, else
the record the workflow runs on), in the collection it writes to.

- Left empty, the kind's first **unique key** is used (the run log says so).
- Left empty on a kind with no unique key, every row makes a new record, as this
  step always did.

Values are compared the way a unique key compares them: a number by its value
(`12` and `12.0` are the same; a column with a blank cell reaches the step as
decimals), so a table re-read from the same file always finds its records. A
number given for a text field is written and matched as its text (`"12"`).

## What an update keeps

An update changes **only the columns in the table**. Every other field on the
matched record (a file, values computed by another workflow) is left exactly as it
is, and an empty cell leaves its field alone instead of clearing it. A row whose
values are already on the record changes nothing: no history entry, and no
workflow triggered; it is counted as `unchanged`.

## Rows it leaves out

A row is skipped, counted in `skipped` and named in `skipped_rows` (the run shows
them as problems), when:

- a field it is matched by is empty in that row;
- its key repeats an earlier row of the same table (the first is saved; the step
  never guesses which of two rows is right);
- several records already have its key;
- the record refuses its values (a restriction, a required field, a unique key).

The other rows are saved.
