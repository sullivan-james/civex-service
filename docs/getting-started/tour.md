# Five-minute tour

This walks through the full path — schema, collection, record, workflow — using a single running example: a `trial` schema for an experiment log. Pick whichever tab matches how you're working; both tabs build the same result, so mixing and matching also works.

## 1. Define a schema

A schema is a template for your data — its field names, types, and validation rules.

=== "CLI"

    ```bash
    civex schema create trial --description "A single experimental trial"
    civex schema add-field trial subject --type string --required
    civex schema add-field trial duration --type float
    civex schema add-field trial result --type string --choices "pass,fail,inconclusive"
    civex schema add-field trial summary --type string
    ```

=== "Web UI"

    Start the server (`civex serve`) and open [http://localhost:8000](http://localhost:8000). Go to **Schemas → New schema**, name it `trial`, then add the `subject` (string, required), `duration` (float), `result` (string, choices `pass,fail,inconclusive`), and `summary` (string) fields from the schema's detail page.

## 2. Create a collection

A collection is a named container for records — a project or experiment run.

=== "CLI"

    ```bash
    civex collection create study-2024 --description "Brazil field season 2024"
    ```

=== "Web UI"

    Go to **Collections → New collection** and name it `study-2024`.

## 3. Add a record

=== "CLI"

    ```bash
    civex record add --to study-2024 --schema trial
    ```

    The CLI prompts for each field in turn — enter a subject, a duration, and a result (`pass`, `fail`, or `inconclusive`). Leave `summary` blank; the workflow below fills it in.

=== "Web UI"

    Open the `study-2024` collection, click **New record**, choose the `trial` schema, and fill in `subject`, `duration`, and `result`. Leave `summary` blank.

## 4. Automate with a workflow

Workflows are YAML files under `_civex/workflows/`. This one copies `result` into `summary` whenever a `trial` record is created — a minimal example of chaining two plugins.

=== "CLI"

    Create `_civex/workflows/trial-summary.yaml`:

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
          value: read_result.value
    ```

    The workflow fires automatically the next time you add or update a `trial` record. Process pending jobs and check the result:

    ```bash
    civex automation run
    civex record show <record-id>
    ```

=== "Web UI"

    Go to **Workflows → New workflow**, paste the same YAML shown in the CLI tab, and save. Trigger it by creating a new `trial` record (or open an existing one and re-save it) — then check the **Runs** page for the job, and the record's detail page for the updated `summary` field.

## What's next

- [Schemas and field types →](../guides/schemas-and-fields.md)
- [Collections and records →](../guides/collections-and-records.md)
- [Workflows →](../guides/workflows.md)
- [Automation →](../guides/automation.md)
- [Server & web UI →](../guides/server-and-web-ui.md)
