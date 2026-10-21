# Get files out as folders, zips or tables

**Goal:** hand a set of files to someone, or open them in another program,
arranged and named by their records rather than by hash, with a table of the
records beside them if you want.

## What the folders look like

Files are laid out by the names of the records they belong to:

```text
North Ridge/                      ← site
  2024-03-15/                     ← visit
    Sample 01/photo.jpg           ← sample, then its file
    Sample 02/photo.jpg
    Sample 03/photo.jpg
Samples.csv                       ← optional table of the records
```

Record names come from each record type's name template. Without one, a folder is
named after the first value, which may just be `1`. Set a template first if the
folders should read well:

```bash
civex schema update sample --display-template "Sample {number:02}"
```

## 1. See what a selection of records holds

```bash
civex files list --in survey-2024
```

```text
Path                                          Size  Where
North Ridge/2024-03-15/Sample 01/photo.jpg  195 KB  new-archive
North Ridge/2024-03-15/Sample 02/photo.jpg  195 KB  new-archive
North Ridge/2024-03-15/Sample 03/photo.jpg    1 KB  new-archive
3 file(s), 392 KB
```

Narrow it the same way for every command on this page: `--in <collection>`,
`--under <record id>` (a record and everything beneath it), `--schema`,
`--field`, `--where field=value`, `--search`, or `--view schema/view` for a
saved filter. Add `--paths` to print where each file is on disk, for scripts.

## 2. Pick how to get them

| You want… | Command | Takes space? |
|---|---|---|
| A folder to open, instantly | `civex files export --in survey-2024 --name photos` | No: hard links on the files' drive |
| Copies you can edit, or on another drive | `… --name photos --mode copy --to archive` | Yes |
| One file to send | `civex files download photos.zip --in survey-2024` | Yes |

A linked folder:

```bash
civex files export --in survey-2024 --name photos --table csv
```

```text
/media/new-archive/civex/_exports/photos on new-archive: 0 copied, 3 linked, 0 already there,
0 removed, 1 table(s) written.
A linked file is the stored file itself: don't edit it in place (use --mode copy for files you will
change).
```

- **Links** are free and instant, but must be on the drive that holds the files.
  If the files are spread over several drives, civex says so and offers a copy,
  or move them onto one drive first with `civex files gather --in survey-2024 --to archive`.
  A drive that can't make links (exFAT, FAT32) is refused before anything is
  built.
- **Running it again** with the same `--name` updates the folder: new files are
  added and ones no longer selected are removed.
- **An unplugged drive:** files that can't be reached are listed first and nothing
  is built unless you agree (or pass `--allow-partial`, which writes a
  `MISSING.txt`).

A zip, with the table inside:

```bash
civex files download photos.zip --in survey-2024 --table csv
```

```text
Wrote photos.zip
      323  Samples.csv
   200000  North Ridge/2024-03-15/Sample 01/photo.jpg
   200000  North Ridge/2024-03-15/Sample 02/photo.jpg
     1000  North Ridge/2024-03-15/Sample 03/photo.jpg
```

## 3. The table

`--table csv` (or `tsv`, `xlsx`, `json`, `jsonl`) writes one table per kind of
record. A file column says where that file is **in the export**, so the table
and the folder always agree:

```text
id,number,photo,taken_at,site
bfcdc007-…,1,North Ridge/2024-03-15/Sample 01/photo.jpg,,North Ridge
f75b804d-…,3,North Ridge/2024-03-15/Sample 03/photo.jpg,2024-03-15T09:30:00+00:00,North Ridge
```

`--column` (repeatable) chooses the columns, including a parent's fields
(`site`) and fields through a reference (`species.common`). `--no-files` makes
the table alone.

## 4. Save it to run again

An export saved with a schema is offered on every record of that kind and the
kinds inside it:

```bash
civex schema exports add site "Photos, flat" --kind sample --field photo --layout flat --table csv
```

```text
Saved site/Photos, flat: photo of sample · flat · csv table
```

Run it on a collection or within one record:

```bash
civex files export --export "site/Photos, flat" --in survey-2024 --name photos
civex files export --export "site/Photos, flat" --under 2d69dc46 --name north-ridge
```

Layouts: `tree` (a folder per record, the default), `grouped` (records holding
files share one folder per kind: `North Ridge/2024-03-15/Samples/…`) or `flat` (one
folder).

## In the app

Use the **Export** menu on any list of records, on a record's page, or on a
collection's **Exports** tab. It takes exactly what the list shows, or the rows
you ticked. From a list, it starts as the table on screen. **Add files or more
tables…** opens the full builder (What · Layout · Finish), with a live preview
of the folder tree. Finish with **Open as folder**, **Copy to a drive** or
**Download**.

Saved exports are on the **Exports** page in the sidebar. Its **Made** tab lists
the folders made, with the space they use.

## Clean up

```bash
civex files exports list
civex files exports remove new-archive/photos     # as listed: where/name
civex files exports remove --older-than 30
```

```text
Name        Where        Files  Links  Copies  Space   Updated
photos-copy  project      3      0      3       392 KB  2026-10-09 11:19
photos      new-archive  4      3      0       0 KB    2026-10-09 11:19
```

Removing a linked folder frees nothing and never touches the stored files.
Anything of yours you added inside an export folder is kept.

## See also

- [Exports](../guides/exports.md): layouts, tables in every folder, and the
  builder in detail.
- [`civex files` reference](../reference/cli/files.md).
