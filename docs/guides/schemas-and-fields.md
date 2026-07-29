# Schemas & fields

A schema defines the structure of a record: what fields it has, what types those fields accept, and any validation rules.

## Creating a schema

=== "CLI"
    ```bash
    civex schema create encounter --description "A single recording session"
    civex schema list
    civex schema show encounter
    ```

=== "Web UI"
    Go to **Schemas → New schema**, enter a name and optional description, and save. The new schema appears in the schema list with a link to its detail page.

The full command list is in the [CLI reference](../cli-reference.md#civex-schema).

## Field types

| Type | Stores | CLI prompt accepts |
|---|---|---|
| `string` | Text | Any text |
| `integer` | Whole number | `42` |
| `float` | Decimal number | `3.14` |
| `boolean` | True/false | `true`, `yes`, `1` / `false`, `no`, `0` |
| `date` | Calendar date | ISO date: `2024-03-15` |
| `datetime` | Point in time (UTC) | ISO datetime: `2024-03-15T09:30:00` |
| `file` | One file attachment | Absolute or relative file path |
| `file_list` | Multiple file attachments | File path (repeat the prompt to add more) |
| `reference` | Link to another record | Record ID or short prefix |

Dates and datetimes are always stored as UTC. Naive datetimes (no timezone suffix) are assumed to be UTC.

## Adding fields

Restrictions constrain what values are accepted when records are saved. They are enforced at write time — for the CLI, the API, and the web UI form alike — never at upload or entry time.

=== "CLI"
    ```bash
    civex schema add-field <schema> <field> --type <type> [--required] [restrictions...]
    ```

    **integer / float**
    ```bash
    civex schema add-field trial score --type integer --min 0 --max 100
    civex schema add-field measurement temp --type float --min -273.15
    ```

    **string**
    ```bash
    # Allow only specific values (renders as a dropdown in the UI)
    civex schema add-field trial outcome --type string --choices "pass,fail,inconclusive"

    # Limit length
    civex schema add-field profile bio --type string --max-length 500
    ```

    **date / datetime**
    ```bash
    # Records must fall within a date range
    civex schema add-field trial start_date --type date --min 2024-01-01 --max 2024-12-31
    ```

    **file / file_list**
    ```bash
    # Only accept specific file types
    civex schema add-field recording audio --type file --accept ".wav,.flac"

    # Limit file size (bytes — 10 MB = 10485760)
    civex schema add-field document pdf --type file --accept ".pdf" --max-size 10485760
    ```

    **reference**
    ```bash
    # Links to a record of another schema
    civex schema add-field selection encounter_id --type reference --references encounter
    ```

=== "Web UI"
    On a schema's detail page, click **Add field**. Enter a name, pick a type from the dropdown, and toggle **Required**. The form reveals the restrictions that apply to the chosen type — min/max for `integer`/`float`, choices/max length for `string`, accept/max size for `file`/`file_list`, and a target-schema picker for `reference`.

The full flag list is in the [CLI reference](../cli-reference.md#civex-schema).

## Editing fields

Rename a field or change its restrictions without losing data.

=== "CLI"
    ```bash
    # Rename
    civex schema update-field trial outcome --rename result

    # Change restrictions (merges with existing; does not affect stored data)
    civex schema update-field trial score --min 0 --max 50

    # Mark optional/required
    civex schema update-field trial subject --optional

    # Remove all restrictions
    civex schema update-field trial score --clear-restrictions
    ```

=== "Web UI"
    Click the pencil icon on any field row to edit it inline — the same name, type, required, and restriction inputs as **Add field**.

## Schema inheritance

Schemas can extend a parent schema. Records of a child schema are linked to a parent record, letting you model hierarchical data.

=== "CLI"
    ```bash
    # Parent schema
    civex schema create encounter

    # Child schema
    civex schema create selection --parent encounter
    civex schema add-field selection start_time --type float --required
    civex schema add-field selection end_time --type float --required
    ```

=== "Web UI"
    On the **New schema** form, pick a **Parent** from the dropdown before saving. The parent field can't be changed later — recreate the schema if you need a different parent.

When you add a `selection` record, civex prompts for the parent `encounter` record ID. The parent's fields are also visible when viewing a child record. Inheritance can be arbitrarily deep — grandchild schemas are supported.

!!! note
    A child schema only stores its own fields. Parent fields live on the parent record. This keeps the data model clean and avoids duplication.

## Deleting fields and schemas

=== "CLI"
    ```bash
    civex schema remove-field trial score
    civex schema delete trial          # deletes the schema; does not delete records
    ```

=== "Web UI"
    Click the **✕** on a field row to remove it, or **Delete schema** on the schema's detail page. Deleting a schema does not delete its records.
