# Schemas & fields

A schema defines the structure of a record: what fields it has, what types those fields accept, and any validation rules.

## Names and labels

Every schema and field carries two identifiers, and they do different jobs.

| | What it is | Constraint | Where it shows up |
|---|---|---|---|
| `name` | The machine key | Lowercase letters, digits and underscores, not starting with a digit | Workflow YAML, CSV headers, name templates, API paths |
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

Renaming a `name` is a real change: stored records are unaffected (they're keyed by field UUID), and any name template that uses it is updated for you, but **any workflow YAML that references the old name must be updated by hand**.

`civex schema lint` reports any schema or field whose name isn't a valid slug — typically rows created before this rule existed, or restored from an older dump. Those names still work; the command just tells you where they are and what a slugified version would look like.

```bash
civex schema lint
```

## Naming records and files

A record has no name field of its own: its name is built from its values by a **template** on the schema. Open a schema's **Naming** tab, or set it from the CLI:

```bash
civex schema update sample --display-template "{site:upper}-{taken_on:YYYY-MM}-{sample_no:03}"
civex schema update sample --clear-display-template   # back to "the first text value"
```

A template is literal text with variables in braces. A variable is a field name, optionally followed by a colon and a format; several formats chain with `|`. Use `{{` and `}}` for a literal brace.

| Write | To get |
|---|---|
| `{site}` | the field's value as entered |
| `{site:upper}`, `{site:lower}`, `{site:title}` | the value in that case |
| `{site:slug}` | `North Ridge` → `north_ridge` |
| `{site:trunc(3)}` | the first 3 characters |
| `{taken_on:YYYY-MM-DD}` | a date or datetime in that pattern (`YYYY MM DD HH mm SS`); a partial date such as `2019-06` stops at the last part it has |
| `{sample_no:03}` | a number padded to 3 digits (`7` → `007`) |
| `{depth:.1f}` | a number with 1 decimal place |
| `{site.code}` | a field of the record that the reference field `site` points at (see below) |
| `{schema}`, `{id}` | the schema's name and the record's short id |

A value a record doesn't have is left out together with the separator beside it, so `{site} - {sample_no}` on a record with no site is just the sample number. A schema with no template uses the first text value on the record. Renaming or deleting a field updates every template that uses it.

Fields a schema inherits from its parent can be used like its own; the builder lists them under "From <parent>" so you can tell them apart.

**Reaching into a referenced record.** If a `reference` field names the schema it points at, `{field.other}` reads a field of that record, so a sample can be named `{site.code}-{sample_no:03}`. It reaches one record deep only: `{site.region.name}` isn't allowed, and a referenced record's own name doesn't expand its references. The value is read when the name is shown, so editing the site renames its samples at once. The reference field has to set its schema (a reference that may point anywhere can't be checked), only single `reference` fields work (not lists), and download names can't use it. Renaming or deleting a field on either schema updates the templates that reach it.

The same builder names **downloads**: a `file` field's *Download file name* rule takes a template too, where `{ext}` is the file's extension. There, a missing value makes the download keep its original name instead of a partial one.

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
| `float` | Decimal number, optionally in a fixed unit | `3.14`, or `1024 ft` when the field has a unit |
| `boolean` | True/false | `true`, `yes`, `1` / `false`, `no`, `0` |
| `date` | Calendar date, or a year or month when the field allows it | ISO date: `2024-03-15` (`2024`, `2024-03` if allowed) |
| `geo` | A point, line or area (GeoJSON) | `56.12, -3.41` (latitude, longitude), `POINT(-3.41 56.12)` or GeoJSON |
| `datetime` | Point in time (UTC) | ISO datetime: `2024-03-15T09:30:00` |
| `file` | One file attachment | Absolute or relative file path |
| `file_list` | Multiple file attachments | File path (repeat the prompt to add more) |
| `reference` | Link to another record | Record ID or short prefix |

**Locations.** A `geo` field holds a GeoJSON geometry in WGS84 (longitude first). Restrict the shapes it accepts with `--geometry-types Point,Polygon` and the area it may fall in with `--bbox WEST,SOUTH,EAST,NORTH`; a west edge greater than the east edge crosses the 180th meridian. In CSV files and exports a point is written as `latitude, longitude`; other shapes are written as GeoJSON.

Locations can be typed in the ways people write them: `56.12, -3.41`, `56.12N 3.41W`, `N56.12 W3.41`, `56°07'12"N 3°24'36"W` or `N 56° 07.2' W 3° 24.6'` (the CLI, CSV import and the web form all read these), as well as `POINT(-3.41 56.12)` and GeoJSON. A point can also carry an `uncertainty_m` (how well the position is known, in metres) and a third coordinate for elevation, negative below sea level for a depth.

**The map editor.** On a record, a location field has an **Edit on map…** button. It opens a map for placing a point, or drawing a line or area; latitude and longitude boxes in decimal degrees, degrees and decimal minutes, or degrees, minutes and seconds (with N/S and E/W boxes, so no one has to remember that west is negative); a table of the points of a line or area with its length or area; **Use my current position** (with the device's accuracy); and **Import from a file** for GeoJSON, GPX, KML and WKT. Nothing changes on the record until you press **Apply**. A field's allowed shapes and area are shown on the map and enforced before you apply. The map draws built-in coastlines and a grid, so it works offline and needs no account. For street-level detail, set a tile server under **Settings → Map** (or `[map]` in `_civex/config.toml`, with `tile_url` and `attribution`); you are responsible for that provider's terms of use, and the public OpenStreetMap servers don't allow heavy use.

**Partial dates.** A `date` field's `precision` names the least precise value it accepts: `year` accepts `2019`, `2019-06` and `2019-06-14`, `month` accepts the last two, and `day` (the default) accepts only full dates. Values are stored as written, never padded to a day. A minimum or maximum applies to the whole period, so `2020` fails a minimum of `2020-03`.

**Units.** A `float` field can have a `unit` such as `m` or `degC`. A field has exactly one unit and every stored value is in it. Conversion happens only where data enters: typing `1024 ft` into a metres field (in the form or the CLI) stores `312.1152`, and the CSV import step asks which unit each mapped column is written in. Nothing already stored is ever converted. Changing a field's unit later only relabels it, for correcting a wrong label; to work in a different unit going forward, add a new field. Units outside the built-in table (for example `umol/kg`) work as plain labels with no conversion.

Datetimes are always stored as UTC instants. What changes with a timezone is how a value *without* a UTC offset (like `2024-03-15T09:30:00`, from a CSV cell, an instrument export or a filename) is read, and how stored values are shown.

**Timezones.** A timestamp from an instrument is usually wall time where it was recorded, not UTC. Set a timezone on the collection so such values land on the right instant, and so every viewer sees the same wall time:

```bash
civex collection create my-study --timezone America/Chicago
civex collection update my-study --timezone Asia/Kolkata
civex collection update my-study --timezone ""   # back to unset
```

A `datetime` field can override the collection's zone with its own **Timezone** setting (in the web UI's field form, or as a `timezone` restriction through the API). For any value, the zone is the field's own, else the collection's, else unset.

- **Unset** behaves as it always has: a value with no offset is read as UTC, and the web UI shows times in the viewer's own timezone.
- A value **with an offset** (`2024-03-15T09:30:00-05:00`) is always converted exactly; the zone is ignored.
- Wall times that don't exist (clocks skip forward) or are ambiguous (clocks go back) are **rejected** rather than guessed. Add an offset to resolve them.
- Changing a collection's timezone does not change stored values, only how they are shown and how future offset-less input is read. Values already stored without an offset are still read as UTC.

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
    On a schema's detail page the fields are listed on the left; select one to see and change its rules on the right. Click **Add field** and choose what kind of data it is (a quantity, a location, a file, and so on); then enter a **label** (the name auto-fills as a slug) and toggle **Required**. The rules offered depend on the kind: min/max and a unit for numbers, precision for dates, shapes and an allowed area for locations, allowed values for text, file types and size for files, and a target schema for links. Unsaved changes are flagged, and you're asked before leaving them.

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
| `--unit SYMBOL` | `float` | Unit every value is stored in, e.g. `m` |
| `--precision year\|month\|day` | `date` | Least precise value accepted |
| `--geometry-types A,B` | `geo` | Shapes accepted, e.g. `Point,Polygon` |
| `--bbox W,S,E,N` | `geo` | Allowed area in degrees |
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
    Select a field in the list to edit it — the same label, name, required, and rule inputs as **Add field**; the type can't change once a field exists. Editing a field never re-derives its name from the label; renaming is always deliberate.

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
    A child schema only stores its own fields. Parent fields live on the parent record. This keeps the data model clean and avoids duplication. Filters, sorts and view columns can still use a parent's fields on its children — civex reads them from the parent record — and can reach the other way too ("encounters that have a selection where…"). See [Browsing a collection](collections-and-records.md#browsing-a-collection).

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
