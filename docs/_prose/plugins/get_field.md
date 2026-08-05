# `civex.get_field`

Read the value of a field from the trigger record. Reach for this whenever a later step needs the record's current data rather than a value produced earlier in the workflow.

<!-- civex:tables -->

```yaml
- id: read_audio
  plugin: civex.get_field
  config:
    field: audio_file
```
