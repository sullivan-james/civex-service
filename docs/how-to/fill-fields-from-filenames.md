# Fill fields from file names

**Goal:** instruments name files after when or where they were made
(`20240315_093000.csv`). Have civex read that into a field every time a file is
attached, so nobody types it.

## Set the rule on the field, once

A text, number, date or date-time field can carry a rule: *fill me from this
file field's name, with this pattern*. From then on, whenever a record is saved
with that field blank and the file attached, the value is read from the file's
name **as part of the same save**, before the field's own rules and the schema's
unique keys are checked. So it works for a required field and for a field that
must be unique, and nothing runs afterwards.

In the app, open the `sample` schema, pick `taken_at` and set **Fill from a
file's name**: choose the file field (`reading`), give the pattern, and try it
on a file name. From a terminal:

```bash
civex schema add-field sample taken_at --type datetime \
    --from-file reading --filename-pattern "YYYYMMDD[-_]HHmmSS"
```

Over the API the rule is a restriction on the field:

```json
{"from_filename": {"field": "reading", "pattern": "YYYYMMDD[-_]HHmmSS"}}
```

Then attach a file and the field is filled:

```text
$ civex record add --to survey-2024 --schema sample
  Parent record ID (visit): 2d69dc46
  number (integer) []: 3
  reading (file) []: /data/20240315_093000.csv
  taken_at (datetime) []:
Added record f75b804d-bff3-42a4-820f-30620587d84a.

$ civex record find --in survey-2024 --schema sample
ID         number  reading               taken_at
f75b804d…  3       20240315_093000.csv  2024-03-15T09:30:00+00:00
```

What the rule does, exactly:

- **A value you type is kept.** Only a blank field is filled. Clearing the
  field and saving again fills it again from the file.
- **A name that fits no pattern leaves the field blank.** If the field is
  required, the save is refused for the missing value, as it would be without
  the rule; otherwise you type the value yourself.
- **A name that fits but doesn't make the field's type** (`sample_ab` for a
  whole number, a 13th month) refuses the save, naming the field, like any other
  value the field doesn't allow.
- **The value is held to the field's other rules** (smallest and largest, allowed
  values) and to the schema's unique keys. A unique key filled from the file name
  is how a second upload of the same reading is caught at once.
- **A list of files gives its first file's name.**
- **The file may be on the record above.** A rule on a child schema may name a
  file field inherited from the parent schema; the name is read from the nearest
  record above that has the file.
- Records that already exist are not touched. The app's **Fill from filename**
  button on a record does one field by hand; for many records at once, see the
  workflow below.

### Patterns

A pattern is searched for anywhere in the name; it needn't describe all of it.
It takes one of three forms:

1. **A token format** (dates and times): `YYYY MM DD HH mm SS` stand for the
   parts of the date, year, month and day required; anything else is a regular
   expression, so `[-_]` takes a dash or an underscore.
   `YYYYMMDD[-_]HHmmSS` reads `20240315_093000.csv`.
2. **A regular expression with named groups** (dates and times, when the tokens
   can't say it): `year`, `month`, `day`, `hour`, `minute`, `second`, as
   `(?P<year>\d{4})`. A pattern that has named groups is read this way.
   `(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})` reads `15.03.2024`.
3. **A regular expression with a capture group** (text and numbers): the first
   group `( )` is the value, or the whole match when there is none.
   `site-([A-Z]+)_` reads `NR` from `site-NR_2024-03-15.jpg`.

Several patterns can be one rule: they are tried in order and the first that
matches wins, so readings named either way are read by one field. Over the API
`pattern` is then a list; the CLI takes the flag more than once:

```bash
civex schema add-field sample taken_at --type datetime --from-file reading \
    --filename-pattern "DDMMYYYY_HHmmSS" --filename-pattern "YYYY-MM-DD"
```

| File name | Field type | `pattern` | Gives |
|---|---|---|---|
| `20240315_093000.csv` | `datetime` | `YYYYMMDD[-_]HHmmSS` | 2024-03-15 09:30:00 |
| `15032024_093000.csv` | `datetime` | `DDMMYYYY_HHmmSS` | 2024-03-15 09:30:00 |
| `site-NR_2024-03-15.jpg` | `date` | `YYYY-MM-DD` | 2024-03-15 |
| `site-NR_2024-03-15.jpg` | `string` | `site-([A-Z]+)_` | `NR` |
| `sample_07.csv` | `integer` | `sample_(\d+)` | 7 |
| `depth_12.5m.csv` | `float` | `depth_([\d.]+)m` | 12.5 |

### Times are read in the collection's timezone

`093000` has no UTC offset. civex reads it in the field's timezone, else the
collection's, else UTC. For an instrument set to local time, set the collection's
timezone first:

```bash
civex collection update survey-2024 --timezone Europe/London
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
a workflow. Save this as `_civex/workflows/read-sample-time.yaml` (or paste it
into **Workflows → New workflow** in the app):

```yaml
name: read-sample-time
description: Read the sample's time from its file name.
triggers:
  record_updated:
    schema: sample
    fields: [reading]        # only when the reading file is set or changed

steps:
  - id: extract
    plugin: civex.extract_from_filename
    config:
      field: reading
      pattern: '(\d{8}[-_]\d{6})'      # 20240315_093000 or 20240315-093000
      output_type: datetime
      date_format: 'YYYYMMDD[-_]HHmmSS'

  - id: save
    plugin: civex.save_field
    config:
      field: taken_at
    inputs:
      value: extract.value             # the extract step's output
```

The plugin reads names with the same tokens as the field rule, in two steps:
`pattern` captures the part of the name, `date_format` reads it. See
[Extract from Filename](../reference/plugins/extract_from_filename.md) for every
option. A workflow runs *after* the record is saved, so it can't fill a required
or unique field in time; the rule above can.

To run it on records you already have, tick them in a list and choose **Run
workflow on N**, or:

```bash
civex workflow run read-sample-time --record bfcdc007
```

The **Runs** page lists every run. A file whose name doesn't fit the pattern
fails that record's run, with the reason:

```text
  → workflow 'read-sample-time' (trigger: manual)
    ✗  plugin_error: Pattern '(\d{8}[-_]\d{6})' did not match filename 'sample1.csv'
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
