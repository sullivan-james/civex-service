# `civex.rows_to_records`

Create one new record per table row. Every row produces a new record; use `civex.upsert_records` instead if you want existing records to be matched and updated rather than duplicated.

> Uses pandas, which ships with civex — see `civex.load_csv`.

<!-- civex:tables -->

```yaml
- id: parse
  plugin: civex.load_csv
  inputs:
    bytes: load.bytes

- id: create
  plugin: civex.rows_to_records
  config:
    schema: Selection
    dataset: field-season-2024
    field_mapping:
      "Begin Time (s)": start_time
      "End Time (s)": end_time
      "Selection": selection_number
  inputs:
    table: parse.table
```
