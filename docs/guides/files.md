# Files

A `file` field holds one file and a `file_list` field holds several. civex stores
the bytes once per drive, named by their content hash, and the record keeps a
reference: `{sha256, filename, size}`. Where the bytes live is covered in
[Storage volumes](storage.md). Getting files back out as folders is in
[Exports](exports.md).

## Attaching files

=== "Web UI"
    On a record's page, drop files on the field (or choose them). Each one
    uploads with progress and is attached at once; there's nothing to save. A
    file the field won't take (wrong type, too big) is refused before uploading.
    You're only asked to confirm when a file would *go*: removing one, or
    replacing a single-file field's file.

    Attaching saves the record, so workflows watching the field run straight
    away.

=== "CLI"
    `civex record add` and `civex record update` ask for a path:

    ```text
      audio (file) []: /data/recordings/20240315_090000.wav
      clips (file_list): /data/clip1.wav
      clips (file_list): /data/clip2.wav
      clips (file_list):                      ← blank to finish
    ```

=== "API"
    Upload, then put the returned reference in the field:

    ```bash
    curl -X POST "http://localhost:8000/api/files?collection=humpbacks" -F "file=@take1.wav"
    # → {"sha256": "3f9c…", "filename": "take1.wav", "size": 200000}
    ```

    `?collection=` sends the file to that collection's home drive.

A removed or replaced file stays stored until
[clean-up](storage.md#cleaning-up) removes it.

## Restricting what a field accepts

```bash
civex schema add-field recording audio --type file --accept ".wav,.flac"
civex schema add-field document pdf --type file --accept ".pdf" --max-size 10485760   # 10 MB
```

`--accept` uses the HTML `accept` format (extensions or MIME types,
case-insensitive). The app checks both before uploading. The API checks them when
the record is saved, not on upload: `POST /api/files` stores any file, and a
record citing one the field doesn't accept is refused.

**Download names.** A file field can rename its file on download with a
template, such as `{species.common}_{site}_{take:02}`, using fields of the record
and the records above it. The stored file and its original name are unchanged.
See [Naming records and files](schemas-and-fields.md#naming-records-and-files).

## Where a file is

With one drive and nothing wrong, the app shows nothing extra. Otherwise:

- A file on a drive that can't be reached is **always** marked with the drive's
  name. Its chip says what to do, such as which drive to plug in.
- With several drives, each file shows a chip naming its drive. Click it for
  where it is, whether it opens, and **More details** (every copy, its path on
  disk, its hash, what else uses it).
- A record whose files are split or unavailable gets a one-line summary:
  `3 files stored on archive (2), default (1) · Split across 2 volumes`.

```bash
civex store where bfcdc007              # a record's files and their drives
civex store where bfcdc007 --details    # + paths on disk, what else uses each
```

Over HTTP, every file value in a record response carries `location`, and
`GET /api/files/{sha256}/info` has the details. `GET /api/files/{sha256}`
downloads the file (`?filename=` names it). It answers 503, naming the drive,
when the file is on one that isn't connected.

## Working on many files: Their files

Above a collection's or record's list of records, **Records | Their files**
switches to the files of exactly the records listed and everything beneath them,
under the same filters. Filter Recordings to `site = North Ridge`, switch, and
you see their audio.

- Each row is a file as stored. A file three records use is one row, and **Used
  by N records** lists them.
- A bar shows where they all are: each drive, an unplugged drive, **not on this
  computer** (for a synced project), and **missing**. Click a place to list only
  its files.
- **Kinds of file** narrows to some file fields.

Tick files, then:

| Action | Does |
|---|---|
| **Move to drive…** | Moves them onto one drive. Only the listed records' references move: a copy other records point at stays where it is |
| **Download to this computer** | Fetches files only on the sync server |
| **Free up space…** | Removes this computer's copies of files the server holds |

The same in a terminal, using the selection options of `civex files`, plus `--on`
for a place and `--name` for a file or record name:

```bash
civex files list   --in humpbacks --on field-ssd
civex files gather --in humpbacks --on field-ssd --to archive
civex files fetch  --under 2d69dc46
civex files free   --in humpbacks --name ".wav"
```

## On a project that syncs

A file another device added downloads when you open or export it, and in the
background for collections this computer keeps. See
[Which files a computer keeps](sync.md#which-files-a-computer-keeps).

## Backing up

Files aren't in `civex dump`. Back up `_civex/objects/` and every volume folder.
See [Back up a project](../how-to/back-up.md).
