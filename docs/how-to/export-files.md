# Get files out as folders, zips or tables

**Goal:** hand a set of files to someone, or open them in another program,
arranged and named by their records rather than by hash, with a table of the
records beside them if you want.

## What the folders look like

Files are laid out by the names of the records they belong to:

```text
South Bay/                        ← encounter
  Take 01/take1.wav               ← recording, then its file
  Take 02/take2.wav
  Take 03/20240315_093000.wav
Recordings.csv                    ← optional table of the records
```

Record names come from each schema's name template. Without one, a folder is
named after the first value, which may just be `1`. Set a template first if the
folders should read well:

```bash
civex schema update recording --display-template "Take {take:02}"
```

## 1. See what a selection holds

```bash
civex files list --in humpbacks
```

```text
Path                                    Size  Where
South Bay/Take 01/take1.wav           195 KB  new-archive
South Bay/Take 02/take2.wav           195 KB  new-archive
South Bay/Take 03/20240315_093000.wav   1 KB  new-archive
3 file(s), 392 KB
```

Narrow it the same way for every command on this page: `--in <collection>`,
`--under <record id>` (a record and everything beneath it), `--schema`,
`--field`, `--where field=value`, `--search`, or `--view schema/view` for a
saved filter. Add `--paths` to print where each file is on disk, for scripts.

## 2. Pick how to get them

| You want… | Command | Takes space? |
|---|---|---|
| A folder to open, instantly | `civex files export --in humpbacks --name takes` | No: hard links on the files' drive |
| Copies you can edit, or on another drive | `… --name takes --mode copy --to archive` | Yes |
| One file to send | `civex files download takes.zip --in humpbacks` | Yes |

A linked folder:

```bash
civex files export --in humpbacks --name takes --table csv
```

```text
/media/new-archive/civex/_exports/takes on new-archive: 0 copied, 3 linked, 0 already there,
0 removed, 1 table(s) written.
A linked file is the stored file itself: don't edit it in place (use --mode copy for files you will
change).
```

- **Links** are free and instant, but must be on the drive that holds the files.
  If the files are spread over several drives, civex says so and offers a copy,
  or move them onto one drive first with `civex files gather --in humpbacks --to archive`.
  A drive that can't make links (exFAT, FAT32) is refused before anything is
  built.
- **Running it again** with the same `--name` updates the folder: new files are
  added and ones no longer selected are removed.
- **An unplugged drive:** files that can't be reached are listed first and nothing
  is built unless you agree (or pass `--allow-partial`, which writes a
  `MISSING.txt`).

A zip, with the table inside:

```bash
civex files download takes.zip --in humpbacks --table csv
```

```text
Wrote takes.zip
      323  Recordings.csv
   200000  South Bay/Take 01/take1.wav
   200000  South Bay/Take 02/take2.wav
     1000  South Bay/Take 03/20240315_093000.wav
```

## 3. The table

`--table csv` (or `tsv`, `xlsx`, `json`, `jsonl`) writes one table per kind of
record. A file column says where that file is **in the export**, so the table
and the folder always agree:

```text
id,take,audio,start_time,site
bfcdc007-…,1,South Bay/Take 01/take1.wav,,South Bay
f75b804d-…,3,South Bay/Take 03/20240315_093000.wav,2024-03-15T09:30:00+00:00,South Bay
```

`--column` (repeatable) chooses the columns, including a parent's fields
(`site`) and fields through a reference (`species.common`). `--no-files` makes
the table alone.

## 4. Save it to run again

An export saved with a schema is offered on every record of that kind and the
kinds inside it:

```bash
civex schema exports add encounter "Audio, flat" --kind recording --field audio --layout flat --table csv
```

```text
Saved encounter/Audio, flat: audio of recording · flat · csv table
```

Run it on a collection or within one record:

```bash
civex files export --export "encounter/Audio, flat" --in humpbacks --name audio
civex files export --export "encounter/Audio, flat" --under 2d69dc46 --name south-bay
```

Layouts: `tree` (a folder per record, the default), `grouped` (records holding
files share one folder per kind: `South Bay/Recordings/…`) or `flat` (one
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
civex files exports remove new-archive/takes     # as listed: where/name
civex files exports remove --older-than 30
```

```text
Name        Where        Files  Links  Copies  Space   Updated
takes-copy  project      3      0      3       392 KB  2026-10-09 11:19
takes       new-archive  4      3      0       0 KB    2026-10-09 11:19
```

Removing a linked folder frees nothing and never touches the stored files.
Anything of yours you added inside an export folder is kept.

## See also

- [Exports](../guides/exports.md): layouts, tables in every folder, and the
  builder in detail.
- [`civex files` reference](../reference/cli/files.md).
