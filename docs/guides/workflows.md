# Workflows

A workflow is a YAML file in `_civex/workflows/` whose steps each run a
[plugin](../reference/plugins/get_field.md). It runs when a record changes, or
when you start it. Runs are covered in [Automation](automation.md).

## A complete example

```yaml
name: read-sample-time
description: Read the sample's time from its file name.

triggers:
  record_updated:
    schema: sample
    fields: [reading]            # only when reading is set or changed

steps:
  - id: extract
    plugin: civex.extract_from_filename
    config:
      field: reading
      pattern: '(\d{8}[-_]\d{6})'
      output_type: datetime
      date_format: 'YYYYMMDD[-_]HHmmSS'

  - id: save
    plugin: civex.save_field
    config:
      field: taken_at
    inputs:
      value: extract.value       # <step id>.<output name>
```

Attaching `20240315_093000.csv` to a sample sets its `taken_at` to
`2024-03-15T09:30:00`. [Fill fields from file names](../how-to/fill-fields-from-filenames.md)
walks through it.

## The file

| Key | Required | Means |
|---|---|---|
| `name` | yes | How the workflow is referred to (`civex workflow run <name>`) |
| `description` | | Shown in lists |
| `enabled` | | `false` switches its triggers off: it runs only when someone starts or tries it. Missing means on |
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
    schema: sample             # every new sample
  record_updated:
    schema: sample
    fields: [reading, photo]   # only when one of these changed
```

Creating a record also fires `record_updated` for each field given a value, so a
`record_updated` trigger on `reading` covers a sample created with its reading
already attached. You don't need both.

Changes that arrive by [sync](sync.md) never trigger workflows. A chain of
workflows triggering each other stops after 10 hops. See
[Stopping automation](automation.md#stopping-automation).

## Manual runs and inputs

```yaml
name: load-samples
record_schema: visit
inputs:
  files:
    type: files                # or: value, a single string or number
    label: CSV files

steps:
  - id: insert
    plugin: civex.create_records_from_files
    config:
      schema: sample
      file_field: reading
    inputs:
      files: __input__.files   # the run's input
```

```bash
civex workflow list
civex workflow run load-samples --record 2d69dc46 --input "files=readings/*.csv"
```

```text
  → workflow 'load-samples' (trigger: manual)
    ✓ done
  → workflow 'read-sample-time' (trigger: record_updated)
    ✓ done
```

Each new sample triggered `read-sample-time`, so the times were filled
in as well.

**In the app:** a record's header has **Run …** for the workflows that fit it. A
workflow with `files` inputs asks for them first, and others start at once. To
run on many records, tick them in a list and choose **Run workflow on N**.

## Editing

In the app, **Workflows → New workflow** offers a few starting points (fill a
field from a file's name, copy a field, put files on matching records, make a
record for each file, run your own plugin on a file, records from a table, or
nothing) and opens the **builder**. The builder is a form:

- **When it runs**: the kind of record it runs on, and whether adding or
  changing one starts it (and which fields to watch).
- **Then, in order**: each step's action, chosen by name ("Read a file",
  "Take a value from a file name"), with a sentence saying what it will do
  with what you chose ("Sets this record's **Recorded on** to **the value it
  took from the name**"), and its settings as lists of your fields and
  schemas. Where a step's input comes from is said in words when only one
  earlier step can give it, and chosen from a list when several can; **Only
  run this step when…** makes it depend on an earlier step's result.
- A setting that is a file-name pattern has **Build from an example…**: pick
  one of the names already in that field and click the part you want (shift+
  click another for several parts; tick **Just the number in it** for `07`
  out of `sel07`). It is found either by its place in the name ("part 2") or
  by the text before it ("after `sel_`"); the one that gives more of the names
  a value like yours is chosen first, and every name is shown with what it
  gives. For files matched to records, names that would give the same key are
  marked. **Write the pattern yourself** takes a regular expression.

**YAML** at the top switches to the file itself, and back: the builder changes
only what it shows, so comments and anything else in the file are kept. A
schema's **Automations** tab has **New workflow for these**, which starts with
that schema chosen.

### Preview

The **Preview** beside the builder runs what is on screen, saved or not, on
the five records of its kind changed last, and runs again a moment after each
change, so you see what a change does as you make it. **Choose records…**
picks up to ten others. For each record it says in a line what it would set
or where it fails, marks the records whose result just changed, and opens to
the full account: each record it would add, change or delete with the values
before and after, files that matched no record, and other workflows its saves
would start. Everything it did is undone each time. A workflow that asks for
files when it starts shows a place to give some. Each workflow's page has the
same preview as a tab.

From the command line, a try runs on one record:

```bash
civex workflow try read-sample-time --record 3f2b8c1e
civex workflow try ./draft.yaml --record 3f2b8c1e --input files='*.csv'
```

A plugin of yours that reaches outside civex (a web request, a file of its
own) still does that during a try.

### On and off

A workflow made in the app starts **off**: nothing starts it by itself until
you turn it on, after trying it (**Turn it on** once the preview fails on
none of its records, or on its page). An existing file without `enabled:` is on. Off, it still runs when
someone starts it.

```bash
civex workflow disable read-sample-time
civex workflow enable read-sample-time
```

Both change only the file's `enabled:` line. To stop every workflow at once,
see [Stopping automation](automation.md#stopping-automation).

Any text editor works too: the app and the builder write the same file, and
changes take effect on the next run with nothing to register. To share
workflows with other computers, see
[the library](sync.md#sharing-workflows-and-plugins). For your own steps, see
[Writing a plugin](../extending/writing-a-plugin.md).
