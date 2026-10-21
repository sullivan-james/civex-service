# `civex.match_files_to_records`

Match each file to an existing child record by extracting a key value from the filename. If a matching record is found, its file field is updated; if not, a new record is created with the key and file field set. Reach for this when files arrive that may correspond to records created by an earlier step (e.g. `civex.rows_to_records` from a sample sheet), rather than always creating new records.

<!-- civex:tables -->

!!! warning "Make the pattern read the whole number"
    A pattern like `sample_([0-9]{2})` reads exactly two digits, so samples 14, 142
    and 149 all give the key `14`. Use `sample_([0-9]+)` (any number of digits). When
    two or more files in one run give the same key, none of them is attached,
    because a record holds one file and there is no telling which is meant. They
    are listed in the `ambiguous` output, each with the files it clashes with, and
    the run says how many there were.

!!! note
    Numeric captures are normalised (e.g. `"042"` → `"42"`) before matching so that integer fields match correctly.

Match photo files like `sample_042_photo.jpg` to Sample records with `number = 42`:
```yaml
- id: match_photos
  plugin: civex.match_files_to_records
  config:
    schema: Sample
    key_field: number
    file_field: photo
    pattern: 'sample_(\d+)'
  inputs:
    files: __input__.files
```
