# Views

A **view** is a saved selection on a schema: which columns to show, how to filter, and how to sort. In the web UI views appear as the **saved filters** above a record list, so the filters a team keeps reaching for are one click away. Views belong to a schema, not to a person or a collection: a view on `recording` applies to every `recording` record, in every collection.

## Creating a view

Open a collection (or a schema's **Browse records** page, which spans every collection), set up the list the way you want it, and click **Save as view…**:

- **Filters** — an AND/OR tree of conditions. A condition can test the schema's own fields, a **parent** record's fields, or **any child** record's fields, so a view on `encounter` can be "encounters that have a selection whose `selection_table` is empty".
- **Columns** — pick fields and their order. A column may be inherited from a parent schema, or join one hop through a `reference` field using dotted notation, e.g. `customer.email`.
- **Sort** — a field, ascending or descending; it may be an inherited field.

Name it however you like — spaces, capitals, punctuation and accents are all fine (`Needs review (QC)`). The only things a name can't contain are `/`, `\` and control characters.

## Using, changing and removing a view

Click a saved filter to apply it; click it again to drop it. Change the filters, sort or columns and the view shows as **modified**: **Save** overwrites it, **Save as view…** makes a new one. Use the **⋮** menu next to the applied view to rename or delete it. Deleting a view only removes the saved selection; no records are affected.

## Exporting a view

=== "CLI"
    ```bash
    civex view export <schema> "<view name>"
    civex view export trial "Active trials" --format json
    civex view export trial active --output active.csv
    ```

    Output defaults to `<view>.csv` (or `.json` with `--format json`). If any column is a `file`/`file_list` field, the export is a `.zip` bundling the data file alongside the referenced attachments instead.

=== "Web UI"
    Apply the view and click **Export**, or export any list you have filtered in a collection — it downloads exactly the rows listed.

Both paths honor the view's saved filter and sort. CSV headers use the dotted `ref_field.target_field` convention for joined columns; JSON nests them instead — `{"customer.email": "a@x"}` becomes `{"customer": {"email": "a@x"}}`.
