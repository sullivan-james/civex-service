# Views

A **view** is a saved column/filter/sort selection against a schema's own fields — a named shortcut for "show me these columns, filtered and sorted this way" without writing the query out each time. Views are scoped to a schema (not a collection): a view over the `trial` schema applies to every `trial` record, across every collection.

Views are created and managed entirely through the web UI; the CLI only exports an already-saved view.

## Creating a view

Open a schema's **Views** page (from the schema's detail page, from a collection's record list once a schema filter is active, or from the top-level **Views** page, which lists saved views for every schema) and click **New view**. The builder has three parts:

- **Columns** — pick which fields to show, and in what order. A column may also join one hop through a `reference` field using dotted notation, e.g. `customer.email` shows the referenced customer's `email` field instead of the raw record ID. Only single-hop joins are supported.
- **Filters** — an AND/OR tree of conditions over the schema's own fields (joined columns can't be filtered on). The live preview updates as you edit.
- **Sort** — one or more fields, each ascending or descending.

Click **Save** to name and persist the selection. Saved views appear in the schema's **Views** list and in the top-level **Views** page, grouped by schema.

## Exporting a view

=== "CLI"
    ```bash
    civex view export <schema> <view-name>
    civex view export trial active --format json
    civex view export trial active --output active.csv
    ```

    Output defaults to `<view>.csv` (or `.json` with `--format json`). If any column is a `file`/`file_list` field, the export is a `.zip` bundling the data file alongside the referenced attachments instead.

=== "Web UI"
    Open the view and click **Export**, choosing CSV or JSON.

Both paths honor the view's saved filter and sort. CSV headers use the dotted `ref_field.target_field` convention for joined columns; JSON nests them instead — `{"customer.email": "a@x"}` becomes `{"customer": {"email": "a@x"}}`.

## Updating and deleting

Open a saved view to edit its columns, filter, or sort, or to rename it — the builder is the same one used to create it. Deleting a view only removes the saved definition; it has no effect on the underlying records.
