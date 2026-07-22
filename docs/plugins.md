# Plugins

A plugin implements one step in a workflow. Civex ships with a set of built-in plugins, and you can [write your own](writing-custom-plugins.md).

Built-in plugins are available in every civex project with no installation required. Plugins that use pandas require the `[workflows]` extra (`pip install 'civex[workflows]'` from source; the desktop app and pre-built binaries include it).

Each entry below shows:

- **Config** — fields you set in the `config:` block of a workflow step.
- **Inputs** — values consumed from previous steps via `inputs:`.
- **Outputs** — values produced, referenced by later steps as `this_step_id.output_name`.

## `civex.get_field`

Read the value of a field from the trigger record.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `field` | string | yes | Name of the field to read |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `value` | any | The field's current value |

```yaml
- id: read_audio
  plugin: civex.get_field
  config:
    field: audio_file
```

---

## `civex.save_field`

Write a single value to a field on the trigger record.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `field` | string | yes | Name of the field to write |

**Inputs**

| Name | Type | Required | Description |
|---|---|---|---|
| `value` | any | yes | The value to write |

```yaml
- id: save_result
  plugin: civex.save_field
  config:
    field: start_time
  inputs:
    value: extract.value
```

---

## `civex.save_fields`

Write multiple fields at once from a dict.

**Inputs**

| Name | Type | Required | Description |
|---|---|---|---|
| `updates` | dict | yes | Mapping of `field_name → value`. Null values are ignored. |

```yaml
- id: save_all
  plugin: civex.save_fields
  inputs:
    updates: build_dict_step.result
```

---

## `civex.load_file`

Load the bytes and metadata from a `file` field on the trigger record.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `field` | string | yes | Name of the `file` field to load |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `bytes` | bytes | Raw file content |
| `filename` | string | Original filename |
| `sha256` | string | Content hash |

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

---

## `civex.load_file_list`

Load file refs from a `file_list` field. Returns the refs as a list without reading the bytes — use `civex.load_file` if you need the actual content.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `field` | string | yes | Name of the `file_list` field |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `files` | list of FileRef | Each entry: `{sha256, filename, size}` |

```yaml
- id: get_clips
  plugin: civex.load_file_list
  config:
    field: audio_clips

- id: process
  plugin: civex.match_files_to_records
  inputs:
    files: get_clips.files
```

---

## `civex.extract_from_filename`

Apply a regex to a file's filename (or a plain string field) and optionally convert the captured value to a typed output. Works with `file`, `file_list`, and `string` fields.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `field` | string | yes | Name of the `file`, `file_list`, or `string` field. For `file_list`, the first file is used. |
| `pattern` | string | no | Regex applied to the filename. Capture group 1 is extracted; if there are no groups, the full match is used. Default: `(.+)` |
| `output_type` | string | no | `string` (default), `integer`, `float`, `date`, or `datetime` |
| `date_format` | string | conditional | Required when `output_type` is `date` or `datetime`. See format tokens below. |

**`date_format` tokens**

| Token | Matches | Example |
|---|---|---|
| `YYYY` | 4-digit year | `2024` |
| `MM` | 2-digit month | `03` |
| `DD` | 2-digit day | `15` |
| `HH` | 2-digit hour (24h) | `09` |
| `mm` | 2-digit minute | `30` |
| `SS` | 2-digit second | `00` |

All other characters in the format string are treated as **raw regex fragments** — not strftime codes. This lets you use `[-_]` to match either a dash or underscore as a separator:

```
YYYYMMDD[-_]HHmmSS   →  matches  20240315-093000  and  20240315_093000
```

Extracted datetimes are stored as UTC ISO 8601 strings.

**Outputs**

| Name | Type | Description |
|---|---|---|
| `value` | converted type | The extracted and converted value |
| `filename` | string | The filename that was parsed |
| `extracted` | string | The raw regex capture before conversion |

**Examples**

Extract a datetime from `20210218_075000_recording.wav`:
```yaml
- id: extract_time
  plugin: civex.extract_from_filename
  config:
    field: audio_file
    pattern: '(\d{8}[-_]\d{6})'
    output_type: datetime
    date_format: 'YYYYMMDD[-_]HHmmSS'
```

Extract a selection number from `sel_042_contour.csv`:
```yaml
- id: extract_num
  plugin: civex.extract_from_filename
  config:
    field: contour_file
    pattern: 'sel_(\d+)'
    output_type: integer
```

---

## `civex.create_records_from_files`

Create one child record per file in a file list. No key matching — every file becomes a new record. Because new records fire `record_updated` on creation, any `record_updated` workflow triggered on the new schema's file field runs automatically for each created record.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `schema` | string | yes | Schema name for the new records |
| `file_field` | string | yes | Field name on the new records to store the file reference |
| `dataset` | string | no | Dataset to create records in. Defaults to the trigger record's dataset. |
| `parent_record_id` | string | no | Parent record ID for child schemas. Defaults to the trigger record's ID. |

**Inputs**

| Name | Type | Required | Description |
|---|---|---|---|
| `files` | list of FileRef | yes | Files to create records from. Typically `__input__.files`. |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `created` | integer | Number of records successfully created |
| `skipped` | integer | Number of files skipped due to validation errors |

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

---

## `civex.match_files_to_records`

Match each file to an existing child record by extracting a key value from the filename. If a matching record is found, its file field is updated. If no match is found, a new record is created with the key and file field set.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `schema` | string | yes | Schema name of the child records to match against |
| `key_field` | string | yes | Field on the child records used for matching |
| `file_field` | string | yes | Field on the child records to set with the matched file |
| `pattern` | string | yes | Regex with one capture group; the capture is the key value |
| `dataset` | string | no | Dataset to search in. Defaults to the trigger record's dataset. |
| `parent_record_id` | string | no | Scope the search to children of this record. Defaults to the trigger record's ID. |

**Inputs**

| Name | Type | Required | Description |
|---|---|---|---|
| `files` | list of FileRef | yes | Files to match |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `created` | integer | Records created (no match found) |
| `updated` | integer | Records updated (match found) |
| `unmatched` | list of string | Filenames that did not match the pattern, or failed validation |

!!! note
    Numeric captures are normalised (e.g. `"042"` → `"42"`) before matching so that integer fields match correctly.

Match contour files like `sel_042_contour.csv` to Selection records with `selection_number = 42`:
```yaml
- id: match_contours
  plugin: civex.match_files_to_records
  config:
    schema: Selection
    key_field: selection_number
    file_field: contour_file
    pattern: 'sel_(\d+)'
  inputs:
    files: __input__.files
```

---

## `civex.load_csv`

Parse a CSV file's bytes into a pandas DataFrame.

> Requires the `[workflows]` extra.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `delimiter` | string | no | Column separator. Default: `,` |
| `encoding` | string | no | File encoding. Default: `utf-8` |

**Inputs**

| Name | Type | Required | Description |
|---|---|---|---|
| `bytes` | bytes | yes | Raw CSV bytes — typically from `civex.load_file` |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `table` | DataFrame | Parsed pandas DataFrame |

```yaml
- id: load
  plugin: civex.load_file
  config:
    field: selection_table

- id: parse
  plugin: civex.load_csv
  inputs:
    bytes: load.bytes
```

---

## `civex.rows_to_records`

Create one record per row in a DataFrame. Every row produces a new record; use `civex.upsert_records` if you want to update existing records instead.

> Requires the `[workflows]` extra.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `schema` | string | yes | Schema name for the new records |
| `dataset` | string | yes | Dataset to create records in |
| `field_mapping` | dict | no | Maps DataFrame column names to schema field names: `{csv_column: schema_field}`. If omitted, column names are used as-is. |
| `parent_record_id` | string | no | Parent record ID. Defaults to the trigger record's ID. |

**Inputs**

| Name | Type | Required | Description |
|---|---|---|---|
| `table` | DataFrame | yes | Source data — typically from `civex.load_csv` |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `created` | integer | Number of records created |

```yaml
- id: parse
  plugin: civex.load_csv
  inputs:
    bytes: load.bytes

- id: create
  plugin: civex.rows_to_records
  config:
    schema: Selection
    dataset: field-season-2024
    field_mapping:
      "Begin Time (s)": start_time
      "End Time (s)": end_time
      "Selection": selection_number
  inputs:
    table: parse.table
```

---

## `civex.upsert_records`

Create or update records from a DataFrame, matching existing records by a key field. If a record with the same key exists in the dataset, it is updated; otherwise a new record is created.

> Requires the `[workflows]` extra.

**Config**

| Field | Type | Required | Description |
|---|---|---|---|
| `schema` | string | yes | Schema name |
| `key_field` | string | yes | Field used to match existing records |
| `dataset` | string | no | Dataset to operate on. Defaults to the trigger record's dataset. |
| `parent_record_id` | string | no | Scope matching to children of this record. Defaults to the trigger record's ID. |

**Inputs**

| Name | Type | Required | Description |
|---|---|---|---|
| `table` | DataFrame | yes | Source data |

**Outputs**

| Name | Type | Description |
|---|---|---|
| `created` | integer | Records created |
| `updated` | integer | Records updated |

```yaml
- id: upsert
  plugin: civex.upsert_records
  config:
    schema: Selection
    key_field: selection_number
  inputs:
    table: parse.table
```

---

## Writing your own

Custom plugins live in `_civex/plugins/*.py` and run as isolated subprocesses — see [Writing custom plugins](writing-custom-plugins.md) for the full guide.
