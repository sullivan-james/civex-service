# Schemas & fields

A schema defines the structure of a record: what fields it has, what types those fields accept, and any validation rules.

## Names and labels

Every schema and field carries two identifiers, and they do different jobs.

| | What it is | Constraint | Where it shows up |
|---|---|---|---|
| `name` | The machine key | Lowercase letters, digits and underscores, not starting with a digit | Workflow YAML, CSV headers, display fields, API paths |
| `label` | The human display name | Free text — spaces, capitals, units, anything | The web UI, `civex schema show`, form labels |

The name is constrained because other things reference it *as text*: a workflow step writes `field: recording_date`, a trigger writes `schema: acoustic_recording`, a CSV column header is the field name. Keeping those as slugs is what makes workflow files readable, diffable in git, and portable between projects.

The label carries everything else. Set it whenever the natural name for something isn't already a slug:

```bash
civex schema create acoustic_recording --label "Acoustic Recording"
civex schema add-field acoustic_recording recording_date --type date --label "Recording Date"
```

If you don't set a label, civex derives one from the name for display — `recording_date` shows as "Recording Date". Labels aren't unique and changing one is always safe, so cosmetic changes should go there rather than into a rename.

!!! tip "Why not reference fields by UUID in workflows?"
    Every field does have a UUID, and record data is stored keyed by it — so renaming a field never touches stored records. But UUIDs in workflow YAML would be unreadable in diffs, unusable in `if:` expressions, and non-portable: a workflow written in one project could never be copied into another. Slug names plus free-text labels give you the readability without giving up clean display text.

### Renaming

Renaming a `name` is a real change: stored records are unaffected (they're keyed by field UUID), and `display_fields` is updated for you, but **any workflow YAML that references the old name must be updated by hand**.

`civex schema lint` reports any schema or field whose name isn't a valid slug — typically rows created before this rule existed, or restored from an older dump. Those names still work; the command just tells you where they are and what a slugified version would look like.

```bash
civex schema lint
```

## Creating a schema

=== "CLI"
    ```bash
    civex schema create encounter --label "Encounter" --description "A single recording session"
    civex schema list
    civex schema show encounter
    ```

=== "Web UI"
    Go to **Schemas → New schema**. Type the display **label** first — the **name** fills itself in as a slug and you can override it. Add an optional description and save. The new schema appears in the schema list with a link to its detail page.

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
    civex schema add-field <schema> <field> --type <type> [--label "Display Name"] [--required] [restrictions...]
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
    On a schema's detail page, click **Add field**. Enter a **label** (the name auto-fills as a slug), pick a type from the dropdown, and toggle **Required**. The form reveals the restrictions that apply to the chosen type — min/max for `integer`/`float`, choices/max length for `string`, accept/max size for `file`/`file_list`, and a target-schema picker for `reference`.

**Restriction flags** (on `add-field` and `update-field`):

| Flag | Applies to | Description |
|---|---|---|
| `--label TEXT` | all | Display name; pass `""` on `update-field` to clear it |
| `--required` / `--optional` | all | Whether the field must be set |
| `--min VALUE` / `--max VALUE` | `integer`, `float` | Value range |
| `--min VALUE` / `--max VALUE` | `date`, `datetime` | Date range (ISO string) |
| `--choices A,B,C` | `string` | Comma-separated allowed values |
| `--max-length N` | `string` | Maximum character length |
| `--accept .ext,.ext` | `file`, `file_list` | Comma-separated allowed extensions |
| `--max-size BYTES` | `file`, `file_list` | Maximum file size in bytes |
| `--references SCHEMA` | `reference` | Target schema name |
| `--clear-restrictions` | all | Remove all restrictions (on `update-field`) |

## Editing fields

Rename a field or change its restrictions without losing data.

=== "CLI"
    ```bash
    # Change the display name only — always safe, nothing references it
    civex schema update-field trial outcome --label "Trial Outcome"

    # Rename the machine key — update any workflow that references it
    civex schema update-field trial outcome --rename result

    # Change restrictions (merges with existing; does not affect stored data)
    civex schema update-field trial score --min 0 --max 50

    # Mark optional/required
    civex schema update-field trial subject --optional

    # Remove all restrictions
    civex schema update-field trial score --clear-restrictions
    ```

=== "Web UI"
    Click the pencil icon on any field row to edit it inline — the same label, name, type, required, and restriction inputs as **Add field**. Editing a field never re-derives its name from the label; renaming is always deliberate.

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
    civex schema delete trial          # moves the schema + its records to Recently Deleted
    civex schema restore trial         # undoes it
    ```

=== "Web UI"
    Click the **✕** on a field row to remove it, or **Delete schema** on the schema's detail page.

Deleting a schema is reversible: it (and every record typed by it, across every collection) moves to **Recently Deleted** rather than being removed outright. See [Deleting & restoring data](deleting-and-restoring.md) for the full cascade and retention rules.
