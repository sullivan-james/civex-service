# `civex.load_csv`

Parse a CSV file's bytes into a pandas DataFrame — the usual first step before `civex.rows_to_records` or `civex.upsert_records`.

> Requires the `[workflows]` extra (`pip install 'civex[workflows]'`). The `import pandas` happens inside `invoke()`, not at module load, so this plugin still registers and appears in workflow validation without pandas installed — it only raises `ImportError` (pointing at the same install command) if a workflow actually runs the step.

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
