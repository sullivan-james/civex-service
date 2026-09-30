# `civex.load_csv`

Parse a CSV file's bytes into a pandas DataFrame — the usual first step before `civex.rows_to_records` or `civex.upsert_records`.

> Requires pandas, which ships with civex. It is imported inside `invoke()`, not at module load, so this plugin registers quickly and validates without loading pandas.

<!-- civex:tables -->

```yaml
- id: load
  plugin: civex.load_file
  config:
    field: selection_table

- id: parse
  plugin: civex.load_csv
  inputs:
    bytes: load.bytes
```
