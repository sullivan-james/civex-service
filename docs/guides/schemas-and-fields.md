# Schemas & fields

A **schema** is a kind of record: its fields, their types and their rules. Schemas
can nest (an Encounter holds Recordings, which hold Selections), and every
record belongs to a [collection](collections-and-records.md).

## A worked example

```bash
civex schema create encounter --label "Encounter"
civex schema add-field encounter site --type string --required
civex schema add-field encounter seen_on --type date --precision month

civex schema create recording --parent encounter --label "Recording"
civex schema add-field recording take --type integer --min 1
civex schema add-field recording audio --type file --accept ".wav,.flac"
civex schema add-field recording depth --type float --unit m --min 0
civex schema update recording --display-template "Take {take:02}"

civex schema show recording
```

```text
Recording (recording)
  Inherits: encounter
Label    Field    Type     Required  Source
Take     take     integer            recording
Audio    audio    file               recording
Depth    depth    float              recording
Site     site     string   yes       ↑ encounter
Seen On  seen_on  date               ↑ encounter
```

**In the app:** **Schemas → New schema**, then **Add field** on the schema's
page. Type the label and the name fills itself in. The rules offered depend on
the kind of field you pick.

## Field types

| Type | In the app | Stores | Typed as |
|---|---|---|---|
| `string` | Text | One line of text | `North Ridge` |
| `longtext` | Text box | Several lines | (newlines kept) |
| `integer` | Whole number | | `42` |
| `float` | Number | Optionally in a fixed unit | `3.14`, `1024 ft` |
| `boolean` | Yes/no | | `yes`, `true`, `1` / `no`, `false`, `0` |
| `date` | Date | A day, or a month or year if allowed | `2024-03-15`, `2024-03`, `2024` |
| `datetime` | Date and time | A UTC instant, to the second | `2024-03-15T09:30:00` |
| `geo` | Location | A GeoJSON point, line or area | `56.12, -3.41` |
| `file` / `file_list` | File / Files | References to stored files | a path |
| `reference` / `reference_list` | Link(s) to records | Record ids | an id or unique prefix |
| `tags` | Tags | A list of short labels | `seal, tagged` |
| `url` | Web address | `http(s)://` text | `https://example.org` |
| `enum` | Choice (legacy) | Use `string` with `--choices` instead | |

## Rules on a field

Rules are checked whenever a record is saved: in the app, the CLI, the API,
imports and workflows.

| Flag | Types | Example |
|---|---|---|
| `--required` / `--optional` | all | |
| `--min` / `--max` | `integer`, `float` | `--min 0 --max 100` |
| `--choices` | `string` | `--choices "pass,fail,inconclusive"` (a dropdown in the app) |
| `--max-length` | `string`, `longtext` | `--max-length 500` |
| `--unit` | `float` | `--unit m`, `--unit degC` |
| `--precision` | `date` | `--precision month` (accepts `2024-03` and `2024-03-15`) |
| `--geometry-types` | `geo` | `--geometry-types Point,Polygon` |
| `--bbox` | `geo` | `--bbox "-12,48,4,62"` (west,south,east,north) |
| `--accept` | `file`, `file_list` | `--accept ".wav,.flac"` |
| `--max-size` | `file`, `file_list` | `--max-size 10485760` (bytes) |
| `--references` | `reference`, `reference_list` | `--references encounter` |

Some rules are set in the app (or over the API, as `restrictions`) only: a
`date`/`datetime` minimum and maximum, a `datetime` field's own timezone, and a
file's download-name template.

### Units

A `float` with a unit stores every value in that unit. Conversion happens only
as data comes in: typing `1024 ft` into a metres field stores `312.1152`, and the
CSV import asks which unit each column is in. Changing a field's unit later
*relabels* it and converts nothing, so to switch units add a new field. Units
civex doesn't know (`umol/kg`) are plain labels.

### Partial dates

`--precision` is the least precise value a date field accepts: `year` takes
`2019`, `2019-06` and `2019-06-14`; `month` the last two; `day` (default) only
full dates. Values are stored as written, never padded. Minimums and maximums
compare whole periods, so `2020` fails a minimum of `2020-03`.

### Times and timezones

A `datetime` is stored as a UTC instant. A value *with* an offset
(`2024-03-15T09:30:00-05:00`) is exact. A value *without* one, from a CSV, an
instrument or a file name, is read as wall time in the field's timezone, else
the collection's, else UTC:

```bash
civex collection update humpbacks --timezone America/Chicago
```

Times that don't exist or happen twice at a DST change are rejected rather than
guessed: add an offset. Changing a timezone changes how values are shown and how
new ones are read, never what is stored.

### Locations

A `geo` field holds GeoJSON in WGS84 (longitude first). It reads the ways people
write coordinates:

```text
56.12, -3.41          56.12N 3.41W          56°07'12"N 3°24'36"W
N 56° 07.2' W 3° 24.6'                      POINT(-3.41 56.12)
```

Exports and CSVs write a point as `lat, lon`, and other shapes as GeoJSON. A point
may carry `uncertainty_m` and an elevation (negative for depth). A `--bbox` with
west greater than east crosses the 180th meridian.

On a record, **Edit on map…** places a point or draws a line or area, takes
coordinates in any format, imports GeoJSON, GPX, KML or WKT, and changes nothing
until **Apply**. The map works offline with built-in coastlines. For street
detail, set a tile server in **Settings → Map** (`[map] tile_url` and
`attribution` in `config.toml`), following that provider's terms.

## Names and labels

| | `name` | `label` |
|---|---|---|
| Is | the machine key | the display name |
| Looks like | `recording_date` (lowercase, digits, `_`) | `Recording Date` (anything) |
| Used by | workflow YAML, CSV headers, templates, API paths | the app, `schema show`, forms |
| Changing it | a real rename (see below) | always safe |

Without a label, one is derived from the name. Records store values by field id,
so a rename never touches stored data, and templates are updated for you. **Workflow
YAML that names the old field must be updated by hand.**

```bash
civex schema update-field recording take --label "Take number"   # safe
civex schema update-field recording take --rename take_no        # update workflows
civex schema lint                                                # names that aren't valid slugs
```

## Naming records and files

A record's name comes from its schema's **template**. It shows in lists,
breadcrumbs, references and export folder names.

```bash
civex schema update sample --display-template "{site.code}-{taken_on:YYYY-MM}-{sample_no:03}"
civex schema update sample --clear-display-template
```

| Write | Gives |
|---|---|
| `{site}` | the value |
| `{site:upper}`, `:lower`, `:title` | `NORTH RIDGE`, … |
| `{site:slug}` | `north_ridge` |
| `{site:trunc(3)}` | `Nor` |
| `{taken_on:YYYY-MM-DD}` | a date pattern (`YYYY MM DD HH mm SS`) |
| `{sample_no:03}`, `{depth:.1f}` | `007`, `12.5` |
| `{site.code}` | a field of the record the reference `site` points at |
| `{schema}`, `{id}` | the schema's name, the record's short id |
| `{{`, `}}` | literal braces |

- A blank value is dropped with the separator beside it: `{site} - {n}` with no
  site gives just `7`.
- The first nameable field you add becomes the template, so new schemas name
  records from the start.
- `{ref.field}` reaches one level through a single `reference` field that names
  its target schema. Editing the target renames at once.
- Renaming or deleting a field updates every template that uses it.

A file field's **download name** (set on the field in the app) uses the same
builder. It names the stem, keeps the file's own extension, and may use fields of
records above and through any reference:
`{species.common}_{site}_{take:02}`.

## Nesting

```bash
civex schema create selection --parent recording
```

A child record sits inside a parent record of the parent schema. A child stores
only its own fields, but filters, sorts, columns and templates can use its
parents' fields, and parents can be filtered by their children ("encounters
that have a selection where…"). The parent can't be changed after creation.

## Keeping records unique

```bash
civex schema add-unique plot site number    # no two plots share both
civex schema unique plot
civex schema remove-unique plot site number
```

In the app: the schema's **Uniqueness** tab.

- Checked among records of that schema **under the same parent**, or for top-level
  records **in the same collection**.
- A record with a blank in any of the rule's fields isn't held to it.
- Only the schema's own scalar fields (text, numbers, dates, yes/no, choices,
  links). Not files, locations, tags or lists.
- You can't add a rule while records already break it. The message names
  clashing records.
- A refused save names the record that already has the values. Workflow steps
  skip such rows and list them in a `duplicates` output.
- A deleted record frees its values. Restoring it is refused if another record
  took them.

## Changing and deleting fields

```bash
civex schema update-field trial score --min 0 --max 50     # merges with existing rules
civex schema update-field trial subject --optional
civex schema update-field trial score --clear-restrictions
civex schema remove-field trial score
civex schema delete trial
```

A field's type can't change. Removing a field is reversible: records keep their
values, shown under **Deleted fields** on the record, and restoring the field
brings them back. A schema delete takes its records to Recently Deleted. See
[Deleting & restoring data](deleting-and-restoring.md).
