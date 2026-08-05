# `civex.upsert_records`

Create or update records from a DataFrame, matching existing records by a key field. If a record with the same key exists in the collection, it is updated; otherwise a new record is created. Reach for this over `civex.rows_to_records` when the same source table gets re-imported over time, e.g. a selection table that grows across a field season.

> Requires the `[workflows]` extra — see `civex.load_csv` for how the pandas dependency is resolved.

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
