# `civex.table@1`  (Table)

Read a table from a spreadsheet or text file: **CSV, TSV or Excel** (`.xlsx`).
The file comes from a **Files** step (connect its `files` output to this step's
`files` input) or, with no input, from a file field of the record the workflow
runs on (`field`). Several files are read and their rows put one after another.

Its output, `table`, feeds **Save as records** (`rows`).

> Uses pandas, which ships with civex. It is imported when the step runs, so the
> step registers quickly without loading pandas.

<!-- civex:tables -->

```yaml
- id: sheet
  plugin: civex.table@1
  config:
    field: sample_sheet     # the file field of this record

- id: save
  plugin: civex.save_records@1
  config:
    schema: Sample
  inputs:
    rows: sheet.table
```

## Text files

By default (`delimiter: auto`) the step works out whether a text file separates
its columns with commas, tabs or semicolons from the file's own lines (fields
inside double quotes are ignored). To fix it, set `delimiter` to one character or
a name (`comma`, `tab`, `semicolon`, `pipe`, `space`; `\t` also means tab), or give
`delimiters` a list the file may use (`[comma, tab]`): the one that splits every
line into the same number of fields wins, then the one that appears most, then the
one listed first. A multi-character `delimiter` is passed to pandas, which reads it
as a regular expression. A byte-order mark at the start of a UTF-8 file (common
from Excel) is dropped, so it doesn't end up in the first column's name.

## Excel files

The first sheet is read, or the one named in `sheet`. The file is recognised by
its name ending in `.xlsx`, `.xlsm` or `.xls`.
