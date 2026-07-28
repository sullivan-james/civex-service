# Workflows

Workflows are YAML files stored in `_civex/workflows/`. Each workflow defines a series of steps — each backed by a plugin — that run in dependency order. Workflows can be triggered automatically when records change, or run manually against a specific record.

## Workflow file structure

```yaml
name: my-workflow
description: Optional human-readable description.

# Optional: restrict manual runs to records of this schema
record_schema: Encounter

# Optional: declare inputs for manual runs
inputs:
  files:
    type: files
    label: Source files
    description: WAV recordings to process.

# Optional: automatic triggers
triggers:
  record_created:
    schema: Recording
  record_updated:
    schema: Recording
    fields:
      - audio_file     # only trigger if this field changed

steps:
  - id: step_one
    plugin: civex.some_plugin
    config:
      field: audio_file

  - id: step_two
    plugin: civex.save_field
    config:
      field: result
    inputs:
      value: step_one.output_name   # reference step_one's output
```

## Triggers

### `record_created`

Fires whenever a record of the given schema is created.

```yaml
triggers:
  record_created:
    schema: Selection
```

### `record_updated`

Fires when a record of the given schema is updated. Add a `fields` list to restrict firing to updates that touch specific fields — only records where at least one of those fields changed will trigger the workflow.

```yaml
triggers:
  record_updated:
    schema: Recording
    fields:
      - audio_file    # only fires if audio_file was set or changed
```

!!! note
    When a record is **created**, civex also fires `record_updated` for any fields that were given a non-null value at creation time. This means a `record_updated` trigger with `fields: [audio_file]` will fire when a new record is created with `audio_file` already filled in — you don't need both `record_created` and `record_updated` declared just to cover creation.

Both `record_created` and `record_updated` can still be declared at the same time if you need to react differently, or if `record_created` doesn't have a `fields` restriction available to it (it always fires, since a newly created record has no "previous" state to diff against).

## Step inputs

Steps pass data to each other using `step_id.output_name` references:

```yaml
steps:
  - id: extract
    plugin: civex.extract_from_filename
    config:
      field: audio_file
      pattern: '(\d{8}[-_]\d{6})'
      output_type: datetime
      date_format: 'YYYYMMDD[-_]HHmmSS'

  - id: save
    plugin: civex.save_field
    config:
      field: start_time
    inputs:
      value: extract.value    # use extract step's "value" output
```

Steps are executed in topological order — if step B declares an input from step A, A always runs first.

## Manual inputs

Declare workflow-level inputs to accept data when running manually (via the UI or `civex workflow run`):

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
      files: __input__.files    # reference the declared input
```

| Type | Accepts |
|---|---|
| `files` | A list of uploaded files (FileRef dicts). In the UI, a multi-file picker is shown. Via CLI, pass a glob pattern with `--input files=*.wav`. |
| `value` | An arbitrary scalar (string, number). |

## Running workflows manually

=== "CLI"
    ```bash
    # Basic run against a record
    civex workflow run my-workflow --record abc123

    # With file inputs (glob pattern)
    civex workflow run load-recordings --record abc123 --input files=recordings/*.wav
    ```

=== "UI"
    Navigate to a record's detail page. The **Workflows** panel lists all workflows compatible with that record's schema. Click **Run** to execute immediately, or supply file inputs when prompted.

## Monitoring jobs

Every workflow execution creates a job. Jobs can be in state `pending`, `running`, `completed`, or `failed`.

```bash
civex automation jobs          # list recent jobs
civex automation run           # process all pending jobs immediately
civex automation logs <job-id> # show a job's captured log output
```

In the UI, the **Runs** page shows all jobs with their logs. The record detail page shows jobs that ran against that specific record.

## Example: extract datetime from a filename

Two workflows work together — one reactive (per record), one for bulk loading.

**`extract-start-time.yml`** — fires automatically when a recording file is attached:
```yaml
name: extract-start-time
triggers:
  record_updated:
    schema: Recording
    fields:
      - audio_file

steps:
  - id: extract
    plugin: civex.extract_from_filename
    config:
      field: audio_file
      pattern: '(\d{8}[-_]\d{6})'
      output_type: datetime
      date_format: 'YYYYMMDD[-_]HHmmSS'

  - id: save
    plugin: civex.save_field
    config:
      field: start_time
    inputs:
      value: extract.value
```

**`load-recordings.yml`** — run manually to bulk-insert recordings (the above workflow fires for each):
```yaml
name: load-recordings
record_schema: Encounter
inputs:
  files:
    type: files
    label: WAV files

steps:
  - id: insert
    plugin: civex.create_records_from_files
    config:
      schema: Recording
      file_field: audio_file
    inputs:
      files: __input__.files
```
