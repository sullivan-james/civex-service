# `civex.upsert_records`

The older name of [`civex.rows_to_records`](rows_to_records.md) matching on one
field: `key_field: number` is `match_on: [number]`. It is kept so workflows saved
with it run as they did, and runs the same code; new workflows use
`civex.rows_to_records`, which also takes several key fields and **Columns to
fields**.

> Uses pandas, which ships with civex — see `civex.parse_table`.

<!-- civex:tables -->

```yaml
- id: upsert
  plugin: civex.upsert_records
  config:
    schema: Sample
    key_field: number
  inputs:
    table: parse.table
```

How rows are matched, what an update keeps and which rows are left out are as
described for [`civex.rows_to_records`](rows_to_records.md). A row with no value
for the key field is now counted in `skipped` and named in `skipped_rows`; it
used to be dropped without a word, and a key repeated in the table used to
overwrite the earlier row's record.
