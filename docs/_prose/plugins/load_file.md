# `civex.load_file`

Load the bytes and metadata from a `file` field on the trigger record. Reach for this when a downstream step (built-in or custom) needs the actual file content, not just its reference.

<!-- civex:tables -->

```yaml
- id: load_reading
  plugin: civex.load_file
  config:
    field: reading

- id: process
  plugin: my.csv_processor
  inputs:
    bytes: load_reading.bytes
    filename: load_reading.filename
```
