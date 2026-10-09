# Workflows

A workflow is a YAML file in `_civex/workflows/` whose steps each run a
[plugin](../reference/plugins/get_field.md). It runs when a record changes, or
when you start it. Runs are covered in [Automation](automation.md).

## A complete example

```yaml
name: extract-start-time
description: Read the recording's start time from its file name.

triggers:
  record_updated:
    schema: recording
    fields: [audio]              # only when audio is set or changed

steps:
  - id: extract
    plugin: civex.extract_from_filename
    config:
      field: audio
      pattern: '(\d{8}[-_]\d{6})'
      output_type: datetime
      date_format: 'YYYYMMDD[-_]HHmmSS'

  - id: save
    plugin: civex.save_field
    config:
      field: start_time
    inputs:
      value: extract.value       # <step id>.<output name>
```

Attaching `20240315_093000.wav` to a recording sets its `start_time` to
`2024-03-15T09:30:00`. [Fill fields from file names](../how-to/fill-fields-from-filenames.md)
walks through it.

## The file

| Key | Required | Means |
|---|---|---|
| `name` | yes | How the workflow is referred to (`civex workflow run <name>`) |
| `description` | | Shown in lists |
| `triggers` | | When it runs by itself (below) |
| `record_schema` | | Manual runs only on records of this schema |
| `inputs` | | What a manual run asks for (below) |
| `steps` | yes | `id`, `plugin`, `config` (the plugin's settings), `inputs` (other steps' outputs) |

Steps run in dependency order: a step that takes `extract.value` runs after
`extract`. Each plugin's settings, inputs and outputs are in the
[plugin reference](../reference/plugins/get_field.md), and `civex plugin list`
shows what's installed here.

## Triggers

```yaml
triggers:
  record_created:
    schema: selection          # every new selection
  record_updated:
    schema: recording
    fields: [audio, notes]     # only when one of these changed
```

Creating a record also fires `record_updated` for each field given a value, so a
`record_updated` trigger on `audio` covers a recording created with its audio
already attached. You don't need both.

Changes that arrive by [sync](sync.md) never trigger workflows. A chain of
workflows triggering each other stops after 10 hops. See
[Stopping automation](automation.md#stopping-automation).

## Manual runs and inputs

```yaml
name: load-recordings
record_schema: encounter
inputs:
  files:
    type: files                # or: value, a single string or number
    label: WAV files

steps:
  - id: insert
    plugin: civex.create_records_from_files
    config:
      schema: recording
      file_field: audio
    inputs:
      files: __input__.files   # the run's input
```

```bash
civex workflow list
civex workflow run load-recordings --record 2d69dc46 --input "files=recordings/*.wav"
```

```text
  → workflow 'load-recordings' (trigger: manual)
    ✓ done
  → workflow 'extract-start-time' (trigger: record_updated)
    ✓ done
```

Each new recording triggered `extract-start-time`, so the start times were filled
in as well.

**In the app:** a record's header has **Run …** for the workflows that fit it. A
workflow with `files` inputs asks for them first, and others start at once. To
run on many records, tick them in a list and choose **Run workflow on N**.

## Editing

Edit the YAML in any editor, or in the app under **Workflows → New workflow** (or
open one). Both write the same file, and changes take effect on the next run with
nothing to register. To share workflows with other computers, see
[the library](sync.md#sharing-workflows-and-plugins). For your own steps, see
[Writing a plugin](../extending/writing-a-plugin.md).
