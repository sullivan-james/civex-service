# Five-minute tour

One example from start to finish: a `trial` schema for an experiment log, a
collection to hold trials, a record, and a workflow that fills a field by itself.
Use the CLI or the app. Both build the same project.

## 1. A schema: what a trial looks like

=== "CLI"

    ```bash
    civex schema create trial --description "A single experimental trial"
    civex schema add-field trial subject --type string --required
    civex schema add-field trial duration --type float --unit s
    civex schema add-field trial result --type string --choices "pass,fail,inconclusive"
    civex schema add-field trial summary --type string
    ```

    ```text
    Created schema 'trial'.
    Added 'subject' (string (required)) to schema 'trial'.
    Added 'duration' (float) {'unit': 's'} to schema 'trial'.
    Added 'result' (string) {'choices': ['pass', 'fail', 'inconclusive']} to schema 'trial'.
    Added 'summary' (string) to schema 'trial'.
    ```

=== "Web UI"

    `civex serve --open`, then **Schemas → New schema**, named `trial`. On its
    page, **Add field** four times: *subject* (text, required), *duration*
    (number, unit `s`), *result* (text, allowed values `pass`, `fail`,
    `inconclusive`) and *summary* (text).

## 2. A collection to hold trials

A collection says which schemas its records may be.

=== "CLI"

    ```bash
    civex collection create study-2024 --schema trial --description "Brazil field season 2024"
    ```

=== "Web UI"

    **Collections → New collection**, named `study-2024`, with **trial** ticked.

## 3. A record

=== "CLI"

    ```bash
    civex record add --to study-2024 --schema trial
    ```

    It asks for each field. Leave `summary` blank, because the workflow below
    fills it in:

    ```text
      subject (string) [required]: S01
      duration (float) []: 12.5
      result (string) []: pass
      summary (string) []:
    Added record f623c8d7-eb75-41e1-b2ec-d6feb7f02f7a.
    ```

=== "Web UI"

    Open `study-2024`, then **New ▸ New trial**. Fill in subject, duration and
    result, leave summary blank, and save.

## 4. A workflow: fill a field automatically

Create `_civex/workflows/trial-summary.yaml` (or paste it into **Workflows → New
workflow**):

```yaml
name: trial-summary
description: Copy the result into the summary field on new trials.

triggers:
  record_created:
    schema: trial

steps:
  - id: read_result
    plugin: civex.get_field
    config:
      field: result

  - id: write_summary
    plugin: civex.save_field
    config:
      field: summary
    inputs:
      value: read_result.value    # the output of the step above
```

Add another trial (step 3 again) and the workflow runs straight away:

```text
Added record f623c8d7-eb75-41e1-b2ec-d6feb7f02f7a.
  → workflow 'trial-summary' (trigger: record_created)
    ✓ done
```

```bash
civex record find --in study-2024 --schema trial
```

```text
ID         subject  duration  result  summary  Created
f623c8d7…  S01      12.5      pass    pass     2026-10-09
```

In the app, the record's `summary` shows `pass`, and **Runs** lists the run.

## Where next

| To… | Read |
|---|---|
| Bring in a spreadsheet or a folder of files | [Import data](../how-to/import-data.md) |
| Model nested data (an encounter's recordings) | [Schemas & fields](../guides/schemas-and-fields.md#nesting) |
| Keep files on an external drive | [Put files on another drive](../how-to/storage-drives.md) |
| Work on several computers | [Sync a project](../how-to/set-up-sync.md) |
| Automate more | [Fill fields from file names](../how-to/fill-fields-from-filenames.md) |
