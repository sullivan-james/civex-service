# Schemas

A schema defines the structure of a record: what fields it has, what types those fields accept, and any validation rules.

## Creating a schema

```bash
civex schema create encounter --description "A single recording session"
civex schema list
civex schema show encounter
```

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

```bash
civex schema add-field <schema> <field> --type <type> [--required] [restrictions...]
```

### Restriction flags

Restrictions constrain what values are accepted when records are saved. They are enforced at write time for both the CLI and the API.

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

## Editing fields

Rename a field or change its restrictions without losing data:

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

## Schema inheritance

Schemas can extend a parent schema. Records of a child schema are linked to a parent record, letting you model hierarchical data.

```bash
# Parent schema
civex schema create encounter

# Child schema
civex schema create selection --parent encounter
civex schema add-field selection start_time --type float --required
civex schema add-field selection end_time --type float --required
```

When you add a `selection` record, civex prompts for the parent `encounter` record ID. The parent's fields are also visible when viewing a child record. Inheritance can be arbitrarily deep — grandchild schemas are supported.

!!! note
    A child schema only stores its own fields. Parent fields live on the parent record. This keeps the data model clean and avoids duplication.

In the UI, click the pencil icon on any field row to edit it inline.

## Deleting fields and schemas

```bash
civex schema remove-field trial score
civex schema delete trial          # deletes the schema; does not delete records
```
