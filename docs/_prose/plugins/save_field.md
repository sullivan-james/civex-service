# `civex.save_field`

Write a single value to a field on the trigger record. Use this to persist the output of an earlier step — for example, a value extracted from a filename or computed by a custom plugin.

<!-- civex:tables -->

```yaml
- id: save_result
  plugin: civex.save_field
  config:
    field: start_time
  inputs:
    value: extract.value
```
