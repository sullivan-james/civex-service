# `civex.save_fields`

Write multiple fields at once from a dict, rather than chaining several `civex.save_field` steps. Reach for this when an earlier step (e.g. a custom plugin) already produces a `{field_name: value}` mapping.

<!-- civex:tables -->

```yaml
- id: save_all
  plugin: civex.save_fields
  inputs:
    updates: build_dict_step.result
```
