# `civex.upsert_records`

Create or update records from a DataFrame, matching existing records by a key field. If a record with the same key exists in the collection, it is updated; otherwise a new record is created. Reach for this over `civex.rows_to_records` when the same source table gets re-imported over time, e.g. a selection table that grows across a field season.

> Uses pandas, which ships with civex — see `civex.parse_table`.

<!-- civex:tables -->

```yaml
- id: upsert
  plugin: civex.upsert_records
  config:
    schema: Selection
    key_field: selection_number
  inputs:
    table: parse.table
```

## What an update keeps

An update changes **only the columns in the table**. Every other field on the
matched record (a file, values computed by another workflow) is left exactly as it
is, and an empty cell leaves its field alone instead of clearing it. A row whose
values are already on the record changes nothing: no history entry, and no
workflow triggered. Only a cell with a value is ever written.
