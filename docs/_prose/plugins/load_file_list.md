# `civex.load_file_list`

Load file refs from a `file_list` field. Returns the refs as a list without reading the bytes — use `civex.load_file` if you need the actual content of a single file, or feed the list into `civex.match_files_to_records` / `civex.create_records_from_files`.

<!-- civex:tables -->

```yaml
- id: get_photos
  plugin: civex.load_file_list
  config:
    field: photos

- id: process
  plugin: civex.match_files_to_records
  inputs:
    files: get_photos.files
```
