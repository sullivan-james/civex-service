# Fill fields from file names

**Goal:** instruments name files after when or where they were made
(`20240315_093000.wav`). Have civex read that into a field every time a file is
attached, so nobody types it.

## Once, by hand

On a record with a file attached, text, number, date and date-time fields have a
**from filename** button. Give it a pattern and it fills the field. No setup is
needed.

## Every time: a workflow

Save this as `_civex/workflows/extract-start-time.yaml` (or paste it into
**Workflows → New workflow** in the app):

```yaml
name: extract-start-time
description: Read the recording's start time from its file name.
triggers:
  record_updated:
    schema: recording
    fields: [audio]          # only when the audio file is set or changed

steps:
  - id: extract
    plugin: civex.extract_from_filename
    config:
      field: audio
      pattern: '(\d{8}[-_]\d{6})'      # 20240315_093000 or 20240315-093000
      output_type: datetime
      date_format: 'YYYYMMDD[-_]HHmmSS'

  - id: save
    plugin: civex.save_field
    config:
      field: start_time
    inputs:
      value: extract.value             # the extract step's output
```

Attach a file and the field fills itself:

```text
$ civex record add --to humpbacks --schema recording
  Parent record ID (encounter): 2d69dc46
  take (integer) []: 3
  audio (file) []: /data/20240315_093000.wav
  start_time (datetime) []:
Added record f75b804d-bff3-42a4-820f-30620587d84a.
  → workflow 'extract-start-time' (trigger: record_updated)
    ✓ done
```

```text
$ civex record find --in humpbacks --schema recording
ID         take  audio                start_time
f75b804d…  3     20240315_093000.wav  2024-03-15T09:30:00+00:00
```

`record_updated` also fires when a record is *created* with the file already
set, so this one trigger covers both cases.

### Times are read in the collection's timezone

`093000` has no UTC offset. civex reads it in the field's timezone, else the
collection's, else UTC. For an instrument set to local time, set the collection's
timezone first:

```bash
civex collection update humpbacks --timezone America/Chicago
```

### Other patterns

| File name | `pattern` | `output_type` / `date_format` | Gives |
|---|---|---|---|
| `20240315_093000.wav` | `(\d{8}[-_]\d{6})` | `datetime` / `YYYYMMDD[-_]HHmmSS` | 2024-03-15 09:30:00 |
| `site-NR_2024-03-15.jpg` | `(\d{4}-\d{2}-\d{2})` | `date` / `YYYY-MM-DD` | 2024-03-15 |
| `site-NR_2024-03-15.jpg` | `site-([A-Z]+)_` | (none: text) | `NR` |

The first capture group is the value. See
[Extract from Filename](../reference/plugins/extract_from_filename.md) for every
option.

## Apply it to records you already have

The trigger only fires on new changes. To run it on existing records, tick them
in a list and choose **Run workflow on N**, or:

```bash
civex workflow run extract-start-time --record bfcdc007
```

## Check it worked

The **Runs** page lists every run. A file whose name doesn't fit the pattern
fails that record's run, with the reason:

```text
  → workflow 'extract-start-time' (trigger: manual)
    ✗  plugin_error: Pattern '(\d{8}[-_]\d{6})' did not match filename 'take1.wav'
```

From a terminal:

```bash
civex automation jobs --status failed
civex automation logs <job-id>
```

## See also

- [Workflows](../guides/workflows.md): triggers, steps and inputs.
- [Automation](../guides/automation.md): runs, failures, stopping loops.
