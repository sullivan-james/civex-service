# Exports

An export turns a selection of records into a folder (or zip) of their files,
named and arranged by the records, with tables of the records beside them if you
want. For a walkthrough, see
[Get files out as folders, zips or tables](../how-to/export-files.md).

## Paths

A file's path is the names of the records above it, then the record that holds
it, then the file's name:

```text
Encounter 7/Recording A/Selection 3/table.txt
```

- Names are the record names shown in the app (the schema's name template).
- The record holding a file is a folder too, so many selections each holding
  `table.txt` never clash.
- Two records with the same name in one place get a short id each
  (`Recording A~3f9c01ab`). Nothing else changes.
- Paths start below where you export from: exporting within Encounter 7 drops
  `Encounter 7/`. Across several collections, the collection's name leads.

## Layouts

| Layout | Gives | Use when |
|---|---|---|
| `tree` (default) | `Encounter 7/Recording A/Selection 3/table.txt` | You want the hierarchy |
| `grouped` | `Encounter 7/Recording A/Selections/table.txt` | Files of one kind together, under their parents |
| `flat` | `table.txt` | One folder for everything |

Where records share a folder (`grouped`, `flat`), two different files with the
same name are told apart by their record (`Selection 2 - table.txt`).

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
| **Rows** | One kind of record, e.g. every Recording |
| **Where it's written** | Once at the top, or in each folder of a kind ("a table of each Recording's Selections") |
| **Columns** | Own fields, fields of the records above, one hop through a reference (`species.common`), `id`, `created_at`, `updated_at` |

A column holding files gives each file's **path in the export**, so the table
and the folder agree. A *details sheet* is a table in a record's own folder with
one field per line. Tables in folders need the `tree` layout.

From the CLI, `--table csv` makes one table per kind at the top. On a saved
export, `--table-of` and `--table-in` set a single table's rows and folder:

```bash
# in each recording's folder, a table of its selections
civex schema exports add encounter "Per recording" --kind selection \
  --table csv --table-of selection --table-in recording
```

For several tables, describe them in JSON:

```bash
civex schema exports add encounter "Sheets" --kind selection --tables-json '[
  {"format": "csv", "kind": "selection", "where": "recording"},
  {"format": "csv", "kind": "selection", "where": "selection", "shape": "fields"}
]'
```

## Saved exports

A saved export belongs to a schema and **starts from** it: it takes that kind
and everything inside it. Saved on Encounter, it is offered on every Encounter,
Recording and Selection page, and on collections that use them. It never names a
collection or a record. Those are where it is *run*.

```bash
civex schema exports add encounter "Contour files" --kind selection --field contour --layout flat
civex schema exports list encounter --available   # every export that runs within an encounter
civex schema exports set encounter "Contour files" --layout grouped
civex schema exports remove encounter "Contour files"

civex files export --export "encounter/Contour files" --in my-collection --name contours
civex files list   --export "encounter/Contour files" --under <encounter id>
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
    1. **What**: one card per kind, top down. Tick the file fields to take and the
       tables to write (*All Recordings in one table*, *A details sheet for each
       Recording*, *A table of each Recording's Selections*). A ticked table shows
       its format, name and **columns** on its row. **Only some Selections…**
       filters.
    2. **Layout**: the three layouts, with pictures.
    3. **Finish**: a live preview of the folder tree with each table in place,
       then **Open as folder**, **Copy to a drive** or **Download**.
- When something is in the way (an unplugged drive, files on several drives),
  one dialog says what and offers the ways forward, including *move them onto
  one drive, then link*.
