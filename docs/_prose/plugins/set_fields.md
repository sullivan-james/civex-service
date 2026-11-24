# `civex.set_fields@1`  (Set fields on this record)

Fill in fields of the record the workflow runs on. Only the fields named change;
every other field is kept, and nothing is written (so nothing is triggered) when
the record already holds the values.

Each value in `fields` is what you type, or `{from_field: other_field}` to copy
another field of the same record. Values worked out by earlier steps can come in
through the inputs: `value` (one value, put in the field named in `field`) and
`updates` (several, as `field: value`; empty values are left alone, so a missing
value never clears a field).

<!-- civex:tables -->

```yaml
- id: copy
  plugin: civex.set_fields@1
  config:
    fields:
      status: reviewed
      summary: {from_field: condition}

- id: when
  plugin: civex.value_from_filename@1
  config:
    field: reading
    pattern: '(\d{8}[-_]\d{6})'
    output_type: datetime
    date_format: 'YYYYMMDD[-_]HHmmSS'

- id: save
  plugin: civex.set_fields@1
  config:
    field: taken_at
  inputs:
    value: when.value
```

## Taking a setting from a field of the record

This is not special to this step: **any setting of any step** may be written as
`{from_field: name}`. When the step runs, civex reads that field of the record the
workflow runs on (as it is by then: an earlier step may have just set it) and uses
it. A field with nothing in it stops the step with a message saying so. (This
replaces the old "Read a field" step.)
