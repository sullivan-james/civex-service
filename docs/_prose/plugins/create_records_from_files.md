# `civex.create_records_from_files`

Create one child record per file in a file list. No key matching — every file becomes a new record. Reach for this over `civex.match_files_to_records` when you know none of the files correspond to existing records, e.g. ingesting a batch of new recordings.

Because new records fire `record_updated` on creation, any `record_updated` workflow triggered on the new schema's file field runs automatically for each created record.

<!-- civex:tables -->

```yaml
inputs:
  files:
    type: files
    label: Recording files

steps:
  - id: insert
    plugin: civex.create_records_from_files
    config:
      schema: Recording
      file_field: audio_file
    inputs:
      files: __input__.files
```
