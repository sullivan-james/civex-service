# `civex.parse_table`

Parse a CSV, TSV or other delimited file's bytes into a pandas DataFrame — the usual first step before `civex.rows_to_records` or `civex.upsert_records`.

> Requires pandas, which ships with civex. It is imported inside `invoke()`, not at module load, so this plugin registers quickly and validates without loading pandas.

<!-- civex:tables -->

```yaml
- id: load
  plugin: civex.load_file
  config:
    field: selection_table

- id: parse
  plugin: civex.parse_table
  inputs:
    bytes: load.bytes
```

## Reading CSV and TSV with one step

Give `delimiters` a list of the separators a file may use, and the step picks the
one the file actually uses, from its own lines (fields inside double quotes are
ignored). A name such as `tab` can stand for the character:

```yaml
- id: parse
  plugin: civex.parse_table
  config:
    delimiters: [comma, tab]
  inputs:
    bytes: load.bytes
```

- The separator is chosen from the first lines: the one that splits every line into
  the same number of fields wins, then the one that appears most, then the one listed
  first. A file that uses none of them (a single column) is read with the first.
- Names: `comma`, `tab`, `semicolon`, `pipe`, `space`, `colon`. `\t` also means tab.
  Each entry in `delimiters` must be one character.
- `delimiter` (singular) still sets one separator, exactly as before, and accepts the
  same names. A multi-character value is still passed to pandas, which reads it as a
  regular expression. `delimiters` overrides `delimiter` when both are set.
- A byte-order mark at the start of a UTF-8 file (common from Excel) is dropped, so
  it doesn't end up in the first column's name.
