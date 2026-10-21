# Fill fields from file names

**Goal:** instruments name files after when or where they were made
(`20240315_093000.wav`). Have civex read that into a field every time a file is
attached, so nobody types it.

## Set the rule on the field, once

A text, number, date or date-time field can carry a rule: *fill me from this
file field's name, with this pattern*. From then on, whenever a record is saved
with that field blank and the file attached, the value is read from the file's
name **as part of the same save**, before the field's own rules and the type's
unique keys are checked. So it works for a required field and for a field that
must be unique, and nothing runs afterwards.

In the app, open the type, pick the field and set **Fill from a file's name**:
choose the file field, give the pattern, and try it on a file name. From a
terminal:

```bash
civex schema add-field recording start_time --type datetime \
    --from-file audio --filename-pattern "YYYYMMDD[-_]HHmmSS"
```

Over the API the rule is a restriction on the field:

```json
{"from_filename": {"field": "audio", "pattern": "YYYYMMDD[-_]HHmmSS"}}
```

Then attach a file and the field is filled:

```text
$ civex record add --to humpbacks --schema recording
  take (integer) []: 3
  audio (file) []: /data/20240315_093000.wav
  start_time (datetime) []:
Added record f75b804d-bff3-42a4-820f-30620587d84a.

$ civex record find --in humpbacks --schema recording
ID         take  audio                start_time
f75b804d…  3     20240315_093000.wav  2024-03-15T09:30:00+00:00
```

What the rule does, exactly:

- **A value you type is kept.** Only a blank field is filled. Clearing the
  field and saving again fills it again from the file.
- **A name that doesn't fit the pattern leaves the field blank.** If the
  field is required, the save is refused for the missing value, as it would be
  without the rule; otherwise you type the value yourself.
- **A name that fits but doesn't make the field's type** (`take_ab` for a whole
  number, a 13th month) refuses the save, naming the field, like any other
  value the field doesn't allow.
- **The value is held to the field's other rules** (smallest and largest, allowed
  values) and to the type's unique keys. A unique key filled from the file name
  is how a second upload of the same recording is caught at once.
- **A list of files gives its first file's name.**
- **The file may be on the record above.** A rule on a child type may name a
  file field inherited from the parent type; the name is read from the nearest
  record above that has the file.
- Records that already exist are not touched. The app's **Fill from filename**
  button on a record does one field by hand; for many records at once, see the
  workflow below.

### Patterns

For a **date or date-time** field the pattern is a token format: `YYYY MM DD HH
mm SS` stand for the parts of the date (year, month and day are required);
anything else is a regular expression, so `[-_]` takes a dash or an underscore.
For a **text or number** field it is a regular expression whose first capture
group `( )` is the value, or the whole match when there is none. The pattern is
searched for anywhere in the name; it needn't describe all of it.

| File name | Field type | `pattern` | Gives |
|---|---|---|---|
| `20240315_093000.wav` | `datetime` | `YYYYMMDD[-_]HHmmSS` | 2024-03-15 09:30:00 |
| `site-NR_2024-03-15.jpg` | `date` | `YYYY-MM-DD` | 2024-03-15 |
| `site-NR_2024-03-15.jpg` | `string` | `site-([A-Z]+)_` | `NR` |
| `rec_take_07.wav` | `integer` | `take_(\d+)` | 7 |
| `depth_12.5m.csv` | `float` | `depth_([\d.]+)m` | 12.5 |

### Times are read in the collection's timezone

`093000` has no UTC offset. civex reads it in the field's timezone, else the
collection's, else UTC. For an instrument set to local time, set the collection's
timezone first:

```bash
civex collection update humpbacks --timezone America/Chicago
```

### Renaming or deleting the file field

Renaming the file field renames it in every rule that reads it. Deleting the
file field drops those rules (the fields themselves stay).

## Once, by hand

On a record with a file attached, text, number, date and date-time fields have a
**Fill from filename** button. Give it a pattern and it fills the field. No
setup is needed, and it works whether or not the field has a rule.

## Many records, or more than one step: a workflow

A rule fills a field as the record is saved. To fill records you already have,
or when the value needs more than one pattern can give (several fields from one
name, a lookup, a calculation), use the `civex.extract_from_filename` plugin in
a workflow. Save this as `_civex/workflows/extract-start-time.yaml` (or paste
it into **Workflows → New workflow** in the app):

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

The plugin reads names with the same tokens as the field rule, in two steps:
`pattern` captures the part of the name, `date_format` reads it. See
[Extract from Filename](../reference/plugins/extract_from_filename.md) for every
option. `record_updated` also fires when a record is *created* with the file
already set, so this one trigger covers both cases, but a workflow runs *after*
the record is saved, so it can't fill a required or unique field in time; the
rule above can.

To run it on existing records, tick them in a list and choose **Run workflow on
N**, or:

```bash
civex workflow run extract-start-time --record bfcdc007
```

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

- [Schemas and fields](../guides/schemas-and-fields.md): every rule a field can carry.
- [Workflows](../guides/workflows.md): triggers, steps and inputs.
- [Automation](../guides/automation.md): runs, failures, stopping loops.
