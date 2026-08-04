# `civex.load_file`

Load the bytes and metadata from a `file` field on the trigger record. Reach for this when a downstream step (built-in or custom) needs the actual file content, not just its reference.

<!-- civex:tables -->

```yaml
- id: load_audio
  plugin: civex.load_file
  config:
    field: audio_file

- id: process
  plugin: my.audio_processor
  inputs:
    bytes: load_audio.bytes
    filename: load_audio.filename
```
