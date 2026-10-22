# Exports

An export turns a selection of records into a folder (or zip) of their files,
named and arranged by the records, with tables of the records beside them if you
want. For a walkthrough, see
[Get files out as folders, zips or tables](../how-to/export-files.md).

## Paths

A file's path is the names of the records above it, then the record that holds
it, then the file's name:

```text
North Ridge/2024-03-15/Sample 03/photo.jpg
```

- Names are the record names shown in the app (the schema's name template).
- The record holding a file is a folder too, so many samples each holding
  `photo.jpg` never clash.
- Two records with the same name in one place get a short id each
  (`2024-03-15~3f9c01ab`). Nothing else changes.
- Paths start below where you export from: exporting within North Ridge drops
  `North Ridge/`. Across several collections, the collection's name leads.

## Layouts

| Layout | Gives | Use when |
|---|---|---|
| `tree` (default) | `North Ridge/2024-03-15/Sample 03/photo.jpg` | You want the hierarchy |
| `grouped` | `North Ridge/2024-03-15/Samples/photo.jpg` | Files of one kind together, under their parents |
| `flat` | `photo.jpg` | One folder for everything |

Where records share a folder (`grouped`, `flat`), two different files with the
same name are told apart by their record (`Sample 02 - photo.jpg`).

## How the folder is made

| Method | How | Space | Where |
|---|---|---|---|
| **Link** (`--mode link`, default) | Hard links to the stored files | None | `_exports/<name>` on the drive holding the files (`_civex/exports/<name>` for the default volume) |
| **Copy** (`--mode copy --to <drive>`) | Real copies | The files' size, checked first | On the drive you pick |
| **Zip** (`civex files download x.zip`) | One file | The files' size | Where you say |

Linked files are ordinary files to Windows, WSL and every program, but they *are*
the stored files, so don't edit them in place. Links can't cross drives: a
selection spread over several drives is refused with `files_scattered`, and you
either copy, or gather the files onto one drive first
(`civex files gather … --to <drive>`, or **Move these files…** in the app).
exFAT and FAT32 drives can't link. Symlinks are never used, because they break
when a drive is unplugged.

An export folder holds a `.civex-export.json` listing what civex put there.
Running the export again updates only the difference, and removing it
(`civex files exports remove`) deletes exactly those files and nothing you
added.

## Tables

Formats: `csv`, `tsv`, `xlsx` (numbers stay numbers), `json` (joined values
nest), `jsonl` (one record per line, for very large tables). A point is written
`lat, lon` and a list as JSON in every format.

A table has three independent choices:

| Choice | Options |
|---|---|
| **Rows** | One kind of record, e.g. every Visit |
| **Where it's written** | Once at the top, or in each folder of a kind ("a table of each Visit's Samples") |
| **Columns** | Own fields, fields of the records above, one hop through a reference (`species.common`), `id`, `created_at`, `updated_at` |

A column holding files gives each file's **path in the export**, so the table
and the folder agree. A *details sheet* is a table in a record's own folder with
one field per line. Tables in folders need the `tree` layout.

From the CLI, `--table csv` makes one table per kind at the top. On a saved
export, `--table-of` and `--table-in` set a single table's rows and folder:

```bash
# in each visit's folder, a table of its samples
civex schema exports add site "Per visit" --kind sample \
  --table csv --table-of sample --table-in visit
```

For several tables, describe them in JSON:

```bash
civex schema exports add site "Sheets" --kind sample --tables-json '[
  {"format": "csv", "kind": "sample", "where": "visit"},
  {"format": "csv", "kind": "sample", "where": "sample", "shape": "fields"}
]'
```

## Saved exports

A saved export belongs to a schema and **starts from** it: it takes that kind
and everything inside it. Saved on Site, it is offered on every Site, Visit
and Sample page, and on collections. It never names a collection or a record;
those are where it is *run*. It also says **how it is handed over**, so running
it asks nothing: `--method link` (a folder of links on the files' drive, the
default), `copy` with `--to <drive>` (real copies), or `zip` (one file). An
export can be saved before there is anything to export; it takes whatever
records and files come later.

```bash
civex schema exports add site "Photo files" --kind sample --field photo --layout flat
civex schema exports add site "For the lab" --method copy --to archive
civex schema exports list site --available   # every export that runs within a site
civex schema exports set site "Photo files" --layout grouped --method zip
civex schema exports remove site "Photo files"

civex files export --export "site/Photo files" --in survey-2024 --name photos
civex files list   --export "site/Photo files" --under <site id>
```

`schema exports add --filter` takes a JSON filter tree. To export what a saved
view lists, use `civex files export --view schema/view`.

## In the app

- **Export** menus are on any list of records (it takes the rows listed, or the
  rows ticked), on a record's page (every file beneath it), and on a
  collection's **Exports** tab.
- The **Exports** page in the sidebar is where exports are defined: **Saved**
  lists them (narrow with **Starts from…**, run with **Run on…**), **Made** lists
  folders on disk and removes them.
- **The builder** has three steps:
    1. **What to include**: one card per kind, top down. Tick the files to
       include and the tables to write (*One spreadsheet of all Visits*, *Each
       Visit's details, as a sheet in its folder*, *A list of each Visit's
       Samples, in its folder*). A ticked table shows its format; **Customise…**
       opens its name and **columns**. **Only some Samples…** adds a filter.
    2. **Layout**: how the folders nest.
    3. **Save**: a name, **how it is handed over** (folder of links, copies on a
       drive, or a zip), and a preview of what it makes with the data you have
       now. With no data yet the preview says so and the export still saves.
- A saved export in an **Export** menu runs straight away, the way it was
  saved. **Export…** in the same menu is a one-time export, which asks how to
  hand it over at the end.
