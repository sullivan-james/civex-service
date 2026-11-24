# Workflows

A workflow is a YAML file in `_civex/workflows/` whose steps each run a
[step](../reference/plugins/value_from_filename.md). It runs when a record changes, or
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
    plugin: civex.value_from_filename@1
    config:
      field: reading
      pattern: '(\d{8}[-_]\d{6})'
      output_type: datetime
      date_format: 'YYYYMMDD[-_]HHmmSS'

  - id: save
    plugin: civex.set_fields@1
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
| `inputs` | | Plain values a manual run asks for (below). Files are asked for by a Files step |
| `steps` | yes | `id`, `plugin`, `config` (the plugin's settings), `inputs` (other steps' outputs) |

Steps run in dependency order: a step that takes `extract.value` runs after
`extract`. Each plugin's settings, inputs and outputs are in the
[step reference](../reference/plugins/value_from_filename.md), and `civex plugin list`
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

steps:
  - id: readings
    plugin: civex.files@1
    config:
      source: run              # chosen each time it is run
      label: CSV files         # what the person is asked for

  - id: insert
    plugin: civex.save_records@1
    config:
      schema: sample
      if_exists: add_new
      file_field: reading
    inputs:
      files: readings.files
```

```bash
civex workflow list
civex workflow run load-samples --record 2d69dc46 --input "readings=readings/*.csv"
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
workflow with a Files step set to be chosen when it is run asks for them first
(drop files in, or, on your own computer, choose a folder: nothing is uploaded and
it is faster for many files), and others start at once. To
run on many records, tick them in a list and choose **Run workflow on N**.

## The built-in steps

Three groups, as the app shows them:

- **Bring in**: [Files](../reference/plugins/files.md) (chosen when run, a folder on
  this computer, or a field of the record) and [Table](../reference/plugins/table.md)
  (CSV, TSV or Excel).
- **Work out**: [Value from the file name](../reference/plugins/value_from_filename.md).
- **Save**: [Save as records](../reference/plugins/save_records.md) (rows or files;
  update, skip or add another when a matching record exists) and
  [Set fields on this record](../reference/plugins/set_fields.md).

Any setting of any step may take its value from a field of the record the workflow
runs on, written `{from_field: name}`.

## Step versions and upgrades

A workflow names a built-in step with its version: `civex.save_records@1`. A step
written without one (`civex.rows_to_records`) is **version 0**: the steps civex had
before steps were versioned. A step's version changes only when what a workflow can
say to it changes (its settings, inputs or outputs), never for a better label or a
bug fix.

When civex loads a workflow file written for older steps, it **rewrites the file for
the newer ones** and logs what it did. The old file is kept next to it as
`<name>.yaml.bak` (never overwritten; a second upgrade makes `.bak2`); backups are
not workflows, and are not shared or synced. A workflow you paste, import or save is
upgraded the same way. An upgrade can turn a step into different steps: `civex.load_file`
and `civex.parse_table` become one **Table** step, `inputs: {x: {type: files}}`
becomes a **Files** step named `x`, and the later steps are rewired. Comments in
the file are not kept in the rewrite (the `.bak` has them). A workflow whose old
steps can't be mapped (for example a step of your own reading `civex.load_file`'s
`filename`) is left exactly as it was, with a message saying which step to edit.

A workflow naming a step version this civex doesn't know (it came from a computer
with a newer civex) is **refused**: "needs a newer civex". It is not run, and not
touched, until civex is updated.

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
