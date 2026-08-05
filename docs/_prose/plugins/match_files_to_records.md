# `civex.match_files_to_records`

Match each file to an existing child record by extracting a key value from the filename. If a matching record is found, its file field is updated; if not, a new record is created with the key and file field set. Reach for this when files arrive that may correspond to records created by an earlier step (e.g. `civex.rows_to_records` from a selection table), rather than always creating new records.

<!-- civex:tables -->

!!! note
    Numeric captures are normalised (e.g. `"042"` → `"42"`) before matching so that integer fields match correctly.

Match contour files like `sel_042_contour.csv` to Selection records with `selection_number = 42`:
```yaml
- id: match_contours
  plugin: civex.match_files_to_records
  config:
    schema: Selection
    key_field: selection_number
    file_field: contour_file
    pattern: 'sel_(\d+)'
  inputs:
    files: __input__.files
```
