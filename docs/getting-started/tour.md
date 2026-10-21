# Five-minute tour

One example from start to finish: a *Sample* schema, a collection to hold
samples, a sample record, and a workflow that fills a field by itself. Use the
app or the CLI; both build the same project.

If you haven't yet, read [Schemas, collections and records](concepts.md)
first: a schema is the blank form, a record is one filled-in copy.

## 1. A schema: what a sample looks like

You do this **once**. Every sample you add afterwards uses this form.

=== "Web UI"

    `civex serve --open`, then **Collections → New collection**, named
    `survey-2024`. On its page press **New ▸ Something else…**, type *Sample*,
    and a blank sample opens. Its form ends with **+ Add field**: add *number*
    (whole number, required), *depth* (number, unit `m`), *condition* (text,
    allowed values `good`, `damaged`, `lost`) and *summary* (text). Each one is
    added to every sample, and together they are the Sample schema, which
    you can see under **Schemas** whenever you want.

=== "CLI"

    ```bash
    civex schema create sample --label "Sample" --description "One physical sample"
    civex schema add-field sample number --type integer --required
    civex schema add-field sample depth --type float --unit m
    civex schema add-field sample condition --type string --choices "good,damaged,lost"
    civex schema add-field sample summary --type string
    ```

    ```text
    Created schema 'sample'.
    Added 'number' (integer (required)) to schema 'sample'.
    Added 'depth' (float) {'unit': 'm'} to schema 'sample'.
    Added 'condition' (string) {'choices': ['good', 'damaged', 'lost']} to schema 'sample'.
    Added 'summary' (string) to schema 'sample'.
    ```

## 2. A collection to hold samples

A collection is the binder. It says which schemas may go in it.

=== "Web UI"

    Already done: the collection was made first, and *Sample* was listed on it
    when you pressed **New ▸ Something else…**.

=== "CLI"

    ```bash
    civex collection create survey-2024 --schema sample --description "2024 field season"
    ```

## 3. A record

This is the step you repeat: one record per sample, on the same form.

=== "Web UI"

    Open `survey-2024`, then **New ▸ Sample**. Fill in number, depth and
    condition, leave summary blank, and save. **Add and add another** keeps the
    form open for the next one.

=== "CLI"

    ```bash
    civex record add --to survey-2024 --schema sample
    ```

    It asks for each field. Leave `summary` blank, because the workflow below
    fills it in:

    ```text
      number (integer) [required]: 1
      depth (float) []: 12.5
      condition (string) []: good
      summary (string) []:
    Added record f623c8d7-eb75-41e1-b2ec-d6feb7f02f7a.
    ```

!!! tip "Not a new schema"
    The second sample is **New ▸ Sample** again. **Something else…** is only
    for a kind of thing the collection doesn't have yet.

## 4. A workflow: fill a field automatically

Create `_civex/workflows/sample-summary.yaml` (or paste it into **Workflows →
New workflow**):

```yaml
name: sample-summary
description: Copy the condition into the summary field on new samples.

triggers:
  record_created:
    schema: sample

steps:
  - id: read_condition
    plugin: civex.get_field
    config:
      field: condition

  - id: write_summary
    plugin: civex.save_field
    config:
      field: summary
    inputs:
      value: read_condition.value    # the output of the step above
```

Add another sample (step 3 again) and the workflow runs straight away:

```text
Added record 9a1c47e2-5b3d-4f08-8e61-0c2d7b5a3f90.
  → workflow 'sample-summary' (trigger: record_created)
    ✓ done
```

```bash
civex record find --in survey-2024 --schema sample
```

```text
ID         number  depth  condition  summary  Created
f623c8d7…  1       12.5   good                2026-10-09
9a1c47e2…  2       8.0    damaged    damaged  2026-10-09
```

In the app, the second sample's `summary` shows `damaged`, and **Runs** lists
the run.

## Where next

| To… | Read |
|---|---|
| Bring in a spreadsheet or a folder of files | [Import data](../how-to/import-data.md) |
| Put samples inside visits and sites | [Schemas & fields](../guides/schemas-and-fields.md#types-inside-other-types) |
| Keep files on an external drive | [Put files on another drive](../how-to/storage-drives.md) |
| Work on several computers | [Sync a project](../how-to/set-up-sync.md) |
| Automate more | [Fill fields from file names](../how-to/fill-fields-from-filenames.md) |
