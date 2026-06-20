# Plugins

A plugin is a Python class that implements one step in a workflow. Civex ships with a set of built-in plugins, and you can write your own.

## Built-in plugins

### `civex.get_field`

Read the value of a field from the trigger record.

```yaml
- id: get_audio
  plugin: civex.get_field
  config:
    field: audio_file
```

**Outputs:** `value` — the field's current value.

---

### `civex.save_field`

Write a value to a field on the trigger record.

```yaml
- id: save_result
  plugin: civex.save_field
  config:
    field: start_time
  inputs:
    value: some_step.value
```

**Inputs:** `value` — the value to write.

---

### `civex.save_fields`

Write multiple fields at once. Inputs are passed as a dict keyed by field name.

---

### `civex.load_file`

Load the bytes and metadata from a `file` field.

```yaml
- id: load
  plugin: civex.load_file
  config:
    field: audio_file
```

**Outputs:** `bytes`, `filename`, `sha256`.

---

### `civex.load_file_list`

Load a list of file refs from a `file_list` field.

**Outputs:** `files` — list of `{sha256, filename, size}` dicts.

---

### `civex.extract_from_filename`

Apply a regex to a filename to extract a value, with optional type conversion.

```yaml
- id: extract
  plugin: civex.extract_from_filename
  config:
    field: audio_file          # file, file_list, or string field
    pattern: '(\d{8}[-_]\d{6})'  # regex; capture group 1 is extracted
    output_type: datetime      # string | integer | float | date | datetime
    date_format: 'YYYYMMDD[-_]HHmmSS'  # required when output_type is date/datetime
```

**`date_format` tokens:** `YYYY`, `MM`, `DD`, `HH`, `mm`, `SS`. Everything else is treated as a raw regex fragment, so `[-_]` matches either a dash or underscore.

**Outputs:** `value` (converted), `filename`, `extracted` (raw capture).

---

### `civex.create_records_from_files`

Create one record per file in a file list. No key matching — pure insert. Triggers on each new record fire automatically.

```yaml
- id: insert
  plugin: civex.create_records_from_files
  config:
    schema: Recording
    file_field: audio_file
    dataset: ""          # defaults to the trigger record's dataset
    parent_record_id: "" # defaults to the trigger record's ID
  inputs:
    files: __input__.files
```

**Inputs:** `files` — list of FileRef dicts.  
**Outputs:** `created`, `skipped`.

---

### `civex.match_files_to_records`

Match each file to an existing child record by extracting a key value from the filename. Updates the file field on matched records; creates new records if no match is found.

```yaml
- id: match
  plugin: civex.match_files_to_records
  config:
    schema: Selection
    key_field: selection_number   # field to match against
    file_field: contour_file      # field to set with the FileRef
    pattern: 'sel_(\d+)'          # regex; capture group 1 is the key value
```

**Inputs:** `files` — list of FileRef dicts.  
**Outputs:** `created`, `updated`, `unmatched`.

---

### `civex.load_csv`

Load a CSV file (from a `file` field) into a pandas DataFrame.

**Outputs:** `table` (DataFrame).  
**Requires:** `pip install 'civex[workflows]'`

---

### `civex.rows_to_records` / `civex.upsert_records`

Convert DataFrame rows to records, or upsert records matched by a key field.

**Inputs:** `table` (DataFrame).  
**Requires:** `pip install 'civex[workflows]'`

---

## Writing a custom plugin

Place a `.py` file in `.civex/plugins/`. It must define a class named `Plugin` that subclasses `BasePlugin`.

```python
from __future__ import annotations

from typing import Any
from pydantic import BaseModel
from civex.plugins.base import BasePlugin, WorkflowContext


class Plugin(BasePlugin):
    id = "my_project.compute_duration"
    name = "Compute Duration"
    category = "transforms"

    class Config(BaseModel):
        start_field: str
        end_field: str

    def run(self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext) -> dict[str, Any]:
        start = ctx.record.data.get(config.start_field, 0)
        end = ctx.record.data.get(config.end_field, 0)
        return {"duration": end - start}
```

Reference the plugin in a workflow step using its `id`:

```yaml
- id: compute
  plugin: my_project.compute_duration
  config:
    start_field: start_time
    end_field: end_time
```

### `WorkflowContext` API

| Attribute / method | Description |
|---|---|
| `ctx.record` | The trigger record (read-only DTO) |
| `ctx.dataset` | The dataset the record belongs to |
| `ctx.get_file(sha256)` | Retrieve file bytes by hash |
| `ctx.update_record(data)` | Write a new data dict to the trigger record |
| `ctx.create_record(dataset, schema, data, parent_record_id)` | Create a new record |
| `ctx.commit()` | Flush changes to the database (the executor calls this after all steps; call it yourself only if you need an intermediate commit) |

!!! warning
    Plugins must not import SQLAlchemy models or access the database session directly. Use only `WorkflowContext` and `ctx._app_ctx` service methods.
