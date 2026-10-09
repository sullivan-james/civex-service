# Files

## How file storage works

Civex uses a content-addressed object store: when you attach a file to a record, the file's bytes are stored in `_civex/objects/<sha256[:2]>/<sha256[2:]>` — the same layout as Git's object store. The record stores a lightweight reference: `{sha256, filename, size}`.

This means:
- **Identical files are stored once.** Attaching the same file to ten records uses disk space once. The one exception is a collection's home drive (below): it keeps its own copy of every file the collection uses.
- **Files are immutable.** The SHA-256 hash is the address; the content never changes.
- **Filenames are cosmetic.** The stored filename is the original name you uploaded, but retrieval is always by hash.

Each volume also has a `manifest.jsonl` at its root — one JSON line per object (`{"sha256", "filename", "size"}`), appended the first time that object is written. Object files themselves carry no filename or extension, so the manifest is what makes a volume directory self-describing on its own: even without the database, the app, or `civex dump`, a plain copy of a volume's files tells you what each blob originally was.

## Volumes and removable drives

Files live on one or more **volumes** — directories, usually on different drives. `civex store list` shows each volume's state; when one is not usable it says why and what to do:

| State | Meaning |
|---|---|
| `online` | Readable and writable. |
| `offline` | The path isn't there — typically a drive that isn't plugged in. Records are unaffected; only that volume's files are unavailable until it returns. |
| `wrong drive` | Something is at the path, but it isn't this volume — a different drive, or an empty mount point. |
| `read-only` / `retired` | Readable, but never written to. |

**Settings → Storage** has three tabs. **Volumes** lists each volume on one row: its state and, when it isn't usable, why and what to do; free space; its place in the write queue; and how many collections use it. A row's menu edits it, adds or removes it from the write queue, or removes it, and the volume's name opens **its own page**, which has everything about that drive in one place: its state (and, if it isn't usable, why and what to do), its space, its part in the write queue, **which collections are on it** with their files, size and share of the drive (and a **Move…** for each), the files on it that nothing uses or that only workflow run history keeps (with a **Clean up…** that clears the unused ones off that drive), and any moves involving it. The page is at `/settings/storage/volumes/<name>`. **Collections** shows, for each collection, which volumes hold its files (a bar split by volume, with a **Gather** shortcut when they are split) and lets you assign it a home volume (see below). **Tasks** is where Civex does things to stored files: two buttons, **Move files…** and **Clean up…** (clearing out files nothing uses, also called garbage collection), above the list of moves with their progress. Each tab has its own address (for example `/settings/storage?tab=collections`), so it can be linked to. Above the tabs, a short list appears only when something needs a look (an unplugged volume that holds files, a volume low on space, a move that is running, paused or was interrupted), each with a link to where it is dealt with.

A volume is recognised by an identity, not by its path. `civex store add` writes a small `.civex-volume` marker (a random id) into the volume and records the same id beside the volume's path in `_civex/config.toml`. A drive is therefore recognised wherever it is mounted, and a different drive mounted at the same path is reported as the wrong drive instead of being written to. Nothing is written to a volume that fails this check, and Civex never creates a missing volume directory on its own — an unmounted drive's path would otherwise be recreated on the wrong disk. (Volumes inside the project, such as the default `_civex/objects`, are always trusted.)

If a volume is reported as the wrong drive but this is in fact the right one — the marker was deleted, or the drive was re-formatted — run `civex store adopt <name>` to rewrite the marker. A volume added before identities existed has none and is checked by path alone until you adopt it.

Uploads skip a volume that isn't usable and go to the next one in the write queue; if none can take the file, the upload fails with the reason for each volume.

### Adding a volume

In **Settings → Storage → Volumes → Add volume**, or

```bash
civex store add archive --path /media/archive-drive/civex --allocated-gb 500 --queue
```

The form has three steps: a name, a folder, and how it is used. **Browse…** opens a folder browser for the machine running Civex, starting from your project, your home folder and the drives that are mounted (with free space; network drives are marked and show where they really live). You can make a new folder there. A browser can't reveal the real path of a folder picked in its own dialog, which is why Civex lists the folders itself.

As you type a path, Civex checks it and says what adding it would involve: whether the folder exists or will be created, whether Civex can write to it, how much room it has, whether it is a separate drive or the same disk as the project, and whether it is already a volume or carries another volume's identity. Anything that would make the add fail is shown before you press the button, and adding it enforces the same rules.

By default a new volume is **not** put in the general write queue, so it can be reserved for particular collections (see below). Tick *Use it for new files in general* (or pass `--queue`) to include it.

#### Network drives

Civex uses a network drive your operating system has already mounted: an NFS or SMB share mounted under `/mnt` or `/Volumes`, a mapped drive letter, or a UNC path on Windows. It doesn't mount shares or keep credentials, so for an address such as `smb://host/share`, mount it first and then choose the folder it appears as.

A network drive can be slow, and it can stop answering. Civex never waits on one for more than a few seconds: a volume that doesn't respond is reported as offline ("not responding"), uploads go to the next volume, and reading files on your other volumes carries on as normal. It returns to normal by itself when the connection does.

### Seeing where a file is stored

A record shows where each of its files lives, without getting in the way:

- A file on a volume that can't be reached right now (an unplugged drive, a network share that stopped answering) is **always** marked, with the volume's name and state. Its download link is replaced by "Unavailable" instead of a link that would fail, and opening it directly says which volume it is on and why it isn't available, not just "not found".
- Once you have more than one volume, each file shows a small chip with the **volume** it is stored on.
- **Click the chip** (or focus it and press Enter) to see, in plain words, where the file is and whether it can be opened. If its drive isn't there, it says why and what to do, such as which drive to plug in, with a link to that volume in Settings. **More details** adds the technical information described below.
- If a drive is unplugged *after* you opened the page, clicking **Download** says so right beside the file, naming the drive, instead of the browser's generic "failed" message. Otherwise the browser downloads the file as usual and a short note says it has started.
- A record whose files are split across volumes, or that has files that can't be opened, gets a one-line summary above its fields ("3 files stored on archive (2), default (1) · Split across 2 volumes").
- With one volume and nothing wrong, nothing extra is shown.

Turn on **Settings → Advanced → Show advanced options** to always see the chips, with the details already open: every place the content is stored, **the file's path on disk** (with a copy button), whether the volume is a network drive, the content hash and size, and **everything that uses the same file**. A file used by several records is stored once, so this is how to see what shares it. Without advanced options, **More details** in the chip's panel shows the same thing.

### Uploading

While a file uploads, the record shows which file, how far it is, how fast, and how long is left, with a **Cancel upload** button. When every byte has arrived it says "Saving to storage…" while the server checks and writes the file, which takes a moment for a large file. Cancelling a batch keeps the files that had already finished.

From the command line, `civex store where <record id>` lists a record's files and the volume each is on, and `--details` adds the path on disk and what else uses each file.

The same information is available from the API: `location` on every file value in a record response, and `GET /files/{sha256}/info` for the details. The location is worked out when the record is read and is never saved with the record.

### Choosing where a collection's files go

By default new files go to the first usable volume in the write queue. To keep a collection's files together — on an archive drive, say — give it a **home volume**: in **Settings → Storage → Collections**, which lists every collection with its home, changes it as soon as you pick another, and can set the same home for several selected collections at once. (A collection's own **Storage** tab shows where its files are and where new ones go, and links straight to that row.) Or from a terminal:

```bash
civex store place set study archive
civex store place set study archive --on-unavailable fail
civex store place list
civex store place clear study
```

A home need not be in the write queue. If the home can't take a file (unplugged, full, the wrong drive), the file goes to the write queue by default (`spill`), so an unplugged drive doesn't stop uploads; with `--on-unavailable fail` the upload is refused instead, so the collection's data is never written anywhere else.

**Each record's file is one copy.** The same content can be stored on more than one drive, and each record's file points at exactly one of those copies. So a collection's files are where its records point, with no guessing: two collections can each keep their own copy of a shared file on their own drive, and the storage pages count each collection on its own copies. A copy that more than one collection's records point at is shown once, under **Shared by several collections**, so a drive's rows add up to what it holds. A file's details list every copy and how many records use each. New files go to the collection's home: content already stored is written again only onto a home that hasn't got it.

**Moving is repointing.** A move points the records it covers (the files you picked, a collection, or everything on a drive you empty) at the target drive. A file is copied there unless the drive already has the same content, in which case nothing is copied and they use that copy (de-duplication). The copy they used before stays while other records still point at it ("copied, not moved") and is removed once nothing does. Before anything runs, the move dialog says how many files are copied, how many are already there, and how much space it frees on other drives. **Clean up** removes copies nothing points at, such as a duplicate left on a drive whose records now use another copy.

Civex knows where every copy is from its own inventory of this computer, so opening a file never searches the drives. Where a file is stored belongs to this computer: it is not part of the record and doesn't sync (another computer may hold the same record's file on a different drive, or only on the server). **Clean up** checks the inventory against what is on the drives and repairs it. Clearing a collection's home moves nothing: its records keep the copies they point at.

Homes are stored in `_civex/config.toml` by collection id (`[store.placement.<id>]`), so renaming a collection changes nothing, and they belong to this machine alongside the volumes they name. Removing a volume that is a home needs `--force` (in the app, the removal dialog says what will happen and asks you to type the volume's name when it holds files), which clears those homes. Nothing is ever deleted from the drive.

### Moving files between volumes

To retire a drive, free up space, or keep a collection's files together, move
them. There are two kinds of move:

- **Empty a volume**: everything on it goes to the volume you choose.
- **Gather a collection**: the collection's files are moved onto one volume.
  Files that a collection kept on a *different* volume also uses stay put unless
  you ask for them, because moving one would only split that collection instead.

In the app this is **Settings → Storage → Tasks** (or **Move files off this
volume…** on a volume's menu; a collection's **Storage** tab links to **Gather**
there). From a terminal:

```bash
civex store move --off old-drive --to archive --dry-run   # what would happen
civex store move --off old-drive --to archive             # do it
civex store move --collection field-notes --to archive
civex store transfers list                                # and show, pause, resume, cancel
civex store transfers run                                 # run any waiting moves in this terminal
civex store collections                                   # which volumes hold each collection's files
```

You always see a preview first: how many files and bytes, where they would go,
and anything that would stop it (a drive that is unplugged or too full).

**Moves run one at a time, in the order you ask for them.** Start a second while
one is running and it waits its turn (it says "Waiting", and how many are ahead);
you can pause or cancel it before it starts. While a move is running, the bar
at the bottom of the app shows it live wherever you are (the same bar that shows
workflow runs): how far it is, how fast, how long is left, with a **Pause** button,
and how many more are waiting.
The terminal shows the same as a progress bar, and Ctrl+C pauses it. If the
server is running when you queue a move from the terminal, whichever of them is
free runs it; if one is already moving files, the other leaves the queue to it
and says so.

**A move can't lose your files.** Each file is copied and checked against its
recorded hash (optionally read back and checked again), recorded in Civex, and
only then removed from where it was. Stopping at any point, whether you pause,
cancel, close the terminal, or lose power, leaves every file either in its old
place, its new place, or both. Resuming picks up where it left off.

- A file that can't be moved (damaged, or gone) is listed with the reason and
  left where it is; the rest carry on.
- If the destination fills up, the next listed one is used, and with none left
  the move pauses. If a drive stops responding it pauses, and a move started in
  the app carries on by itself when the drive is back.
- While a volume is being emptied it is made read-only so new files don't keep
  arriving. It is put back as it was as soon as the move stops, whether it
  finished, was paused, was cancelled or failed, so a paused move never leaves a
  drive locked; resuming makes it read-only again.
- Press **Ctrl+C** in the terminal to pause rather than quit.

### Cleaning up unused files

A file stays in storage even after nothing uses it any more (its record was
purged, or the file was replaced). Clean-up deletes those files to free the
space. In the app, **Clean up…** is on **Settings → Storage → Tasks** (every
volume) and on a volume's own page next to its *Unused* row (that volume only).
It looks first, by itself, and says what it found, for example "12 files
(3.4 GB) on 'archive' are not used by any record or workflow run". One button
then deletes exactly those, and it tells you how much space that freed.

- A file used by a record (including one in *Recently deleted*) or by a
  workflow run is never touched.
- Files added in the last 14 days are kept, because a file just uploaded may
  not be attached to its record yet. **Options** changes the number of days.
- A file that only old history (the audit log, an old workflow log) refers to
  counts as unused, so that history may later point at a file that is gone.
- It can't run while a move is in progress; it says so and you try again after.

```bash
civex store gc                       # what would be deleted, from every volume
civex store gc --volume archive      # only what is on 'archive'
civex store gc --volume archive --apply
```

## File field types

| Type | Stores |
|---|---|
| `file` | A single file attachment |
| `file_list` | Multiple file attachments |

## Attaching files

=== "CLI"
    For a `file` field, pass the file path when prompted:

    ```
      audio (file) [required]: /data/recordings/20240315_090000.wav
    ```

    For a `file_list` field, the prompt repeats until you leave it blank:

    ```
      audio_clips (file_list): /data/clip1.wav
      audio_clips (file_list): /data/clip2.wav
      audio_clips (file_list):        ← blank to finish
    ```

=== "Web UI"
    On a new record's form, file fields show a file picker, and the files are attached when you save the form. On an existing record's detail page, a field has a drop zone: choose a file or drop one on it and it is uploaded and attached at once, with progress, like any other edit. There is nothing to approve. A file the field won't take (the wrong type, or over its size limit) is refused before anything is uploaded, with the reason. The only time you are asked first is when a file would go: **removing** one, or **replacing** the one in a single-file field (which removes the current file). Adding to a `file_list` field asks nothing. Because attaching saves the record, workflows that watch the field run when the file is attached. A removed file stays in the object store until garbage collection removes it. Multiple files can be attached to a `file_list` field at once.

## Finding files by name and folder

Files are stored by their content hash, but you don't have to browse them that way. Every file can be reached by the path its records give it: the names of the records above it, then the file's own name. A selection table on a selection in a recording in an encounter is `Encounter 7/Recording A/Selection 3/table.txt`. A record's name is the one you see in the UI; if two records in the same place would share a name, only those two get a short id added (`Recording A~3f9c01ab`).

There are two ways to get a folder of them, and you choose:

- **Open in folder** makes a folder of *links* on the drive that holds the files. Nothing is copied, so it is instant and takes no space. A link is the stored file under another name, so Windows and other programs treat it as an ordinary file. The catch: a linked folder has to be on the same drive as its files, so files spread over **more than one drive can't be gathered this way** (you're told, and offered a copy instead), and a drive that can't make links (exFAT, FAT32) is refused before anything is built. Don't edit a linked file in place: saving over it changes the stored file.
- **Copy to a drive** makes real copies on one drive you choose, wherever the files are now. They take space (you're shown how much, and refused if it won't fit) and are yours to edit.

When the files you want are on several drives, you don't have to move whole collections to get a linked folder. **Move these files…** (or `civex files gather --to <drive>`) moves *only the files in your current selection*, and only the ones not already there, onto one drive. It is an ordinary move: each file is checked before the original is removed, it queues behind any other move, and you can pause it. When it has finished, **Open in folder** links the whole selection.

=== "Web UI"
    The **Export** menu is on a record's page (an Encounter offers every file beneath it), on any list of records (beside **Columns**, so it takes exactly the rows the filters leave, or the rows you have ticked), and on a collection's **Exports** tab. It offers the exports saved for that kind of record, **Export…** for a one-off, **Set up exports…** and **Manage exports…**.

    From a list, **Export…** starts as just the table you're looking at (its format and file name, ready to download) with **Add files or more tables…** to expand it. Saved exports and the other **Export…** buttons open the same builder as the **Exports** page: What, Layout, then Finish, where you choose how to get the result: **Open as folder** (links), **Copy to a drive** (pick the drive), or **Download** (a zip, or the table itself when that is all there is). From a list, the table starts as the columns and order you are looking at. A saved export opens already filled in, on the last step.

    Choosing does the work straight away, in the background. If it takes more than a second, the bar at the bottom of the screen shows "Preparing files…", and moves show how far they are. When nothing is in the way the folder simply opens.

    When something needs a decision, **one** dialog opens with everything in it: what the selection holds and where; any files that can't be reached, with **Check again** once you've plugged the drive in; and how you'd like the folder: *link them where they are*, *move them onto one drive, then link* (only when they're on several drives; it moves just these files, queues like any move, and opens the folder when it has finished), or *copy them onto a drive*. Nothing is built or opened until you choose.

=== "CLI"
    ```bash
    # Every selection table under one encounter; paths start below it
    civex files list --under <encounter id> --schema selection --field selection_table

    # Where those files are on disk right now, one path per line, for scripts
    civex files list --under <encounter id> --schema selection --paths

    # A linked folder, on the drive that holds them
    civex files export --under <encounter id> --schema selection --name tables

    # Real copies on one drive (civex store list shows the drives)
    civex files export --under <encounter id> --schema selection --name tables \
        --mode copy --to archive
    ```

    Add `--table csv` (or `tsv`, `xlsx`, `json`, `jsonl`) to put a table of the records in the folder too, `--column` (repeatable) to choose its columns, and `--no-files` for the table alone. `civex files download <file>` writes the same thing as one file: a zip, or the table itself.

    Running `export` again with the same name updates that folder: new files are added and files no longer selected are removed. A folder holding other files is refused, so nothing of yours is touched. If some files can't be reached, they are listed first and nothing is made unless you agree (or pass `--allow-partial`); the folder then holds a `MISSING.txt`, and the command exits with status 2.

### Tables beside the files

An export can also make a **table** of the records its files belong to, in the same folder (or zip) as the files. Tick **Table of the records** in the builder's first step, choose a format, and, when the rows are of one kind of record, which columns:

| Format | Good for |
|---|---|
| CSV | Opens anywhere. |
| Excel (`.xlsx`) | A spreadsheet, numbers kept as numbers. |
| TSV | Like CSV, tab-separated. |
| JSON | Programs; joined values nest inside their record. |
| JSON Lines | One record per line, for very large tables. |

There is one table for each kind of record, named for the kind (`Selections.csv`). Columns are the record's fields, one hop through a reference (`customer.email`), and the record's `id`, `created_at` and `updated_at`; left alone, a table has the id and every field. A column that holds files says **where each file is in the export** (`Encounter 7/Recording A/table.txt`), so the table and the folder always agree. A list or point is written the same way in every format (a point as `lat, lon`, a list as JSON), never as program text. Untick **Files** to make the table alone: from a list of records that hold no files that is all there is.

A table is part of the export, so it is rewritten when you run the export again, and removed with the folder.

#### Choosing which tables, and where they go

The first step of the builder shows each kind of record (Encounter, then the Recording inside it, then the Selection inside that) as a card of its own, saying where it sits ("Inside Encounter › Recording"). Each card has the **files** to take and the **tables** to write, as rows you tick (click anywhere on the row):

- **Files**: one row per file field that kind defines. Untick the ones you don't want; untick them all to make tables alone.
- **All Recordings in one table**: a single file at the top with a row for every recording.
- **A details sheet for each Recording**: in each recording's folder, its fields (and those of the kinds above it, such as its encounter's site) one per line, as field and value.
- **A table of each Recording's Selections**: in each recording's folder, a table with a row for every selection inside it.

When a table is ticked, its own **Format** (CSV, Excel, …) and **File name** appear on the same row. The name is optional; left empty, a table is named for what it holds (`Recordings`, `Metadata`). A name may use `{schema}`, `{id}` and fields of the folder's record, like `{rname} selections`, for tables written in folders. Columns start as every field.

A table written in each folder needs the layout with a folder per record, so ticking one switches the layout to that and the other two are not offered. A recording with no selections gets no list.

**Columns** are chosen on the table's own row: **All columns** opens one list. The columns shown are at the top in the order they will have (drag, or use the arrows, to move one; untick to take it out), and the ones not shown are below with a search, grouped by where they come from (the record itself, the kinds above it, linked records). Shift-click picks a run. **Only some Selections…** (inside the card whose files you're taking, when they all come from one kind) narrows which records the files come from. A list in each folder can also be made for folders with nothing to list. Any table the rows above don't stand for (an older export's table of "each kind taken") appears under **Other tables**, where it can be changed or removed.

### Saved exports

The **Exports** page (in the sidebar) lists every saved export as a table, like the other lists: search it, narrow it with **Starts from…**, sort by a column, and choose a collection under **Run on…** to enable **Run…** on each row. An export **starts from** a kind of record, such as an Encounter: it takes that kind and everything inside it, and is offered on every Encounter, Recording and Selection page and on collections that use them. **New export** opens the builder, whose first question is **Starts from** (the kinds are shown as they nest, and a sentence under it says what that means), then three steps:

1. **What**: your folders, level by level, with the **files** to take and the **tables** to write ticked at each (see above).
2. **Layout**: three pictures of the folder each layout makes.
    - **A folder per record**: a folder for every level, then the files.
    - **Grouped by kind**: the folders above are kept, but the records that hold the files share one folder named for their kind (`Parent 1/Child 1/Items/…`).
    - **All in one folder**: just the files.

    Where several records share a folder and two different files have the same name, each is named for its record (`Item 2 - file.txt`).
3. **Finish**: a name, a summary, and what it makes: the folder as a tree you can open and close, worked out against your data as soon as you arrive and kept up to date as you change things. Each table sits in the folder it will be written in, with its row count.

An export doesn't say which collection or record it runs on. It is offered where you are: on the **Exports** page (choose a collection to run on) and a **collection's Exports tab** (run on the whole collection), and in the **Files menu** of every record of that schema and the schemas below it, down to the kind that holds the files, run on the record you're looking at. Save "Contour files, in one folder" with Encounter, and every Encounter, Recording and Selection page offers it.

On the command line:

```bash
civex schema exports add encounter "Contour files" --kind selection --field contour --layout flat
civex schema exports add encounter "Selection tables" --kind selection --table xlsx --column sname --column quality --no-files
# A table of each recording's selections, and a metadata sheet for each selection
civex schema exports add encounter "Sheets" --kind selection --tables-json \
  '[{"format": "csv", "kind": "selection", "where": "recording"},
    {"format": "csv", "kind": "selection", "where": "selection", "shape": "fields"}]'
civex schema exports list encounter            # add --available for every export that runs within an encounter
civex schema exports set encounter "Contour files" --layout grouped
civex schema exports remove encounter "Contour files"

# Run one on a collection, or within a record
civex files export --export encounter/"Contour files" --in my-collection --name contours
civex files list --export encounter/"Contour files" --under <encounter id>
```

`--filter` takes a JSON filter tree; `--layout` on `civex files` overrides a saved export's layout. A saved view works the same way with `--view schema/view`.

### Cleaning up exports

Exports are folders civex made in its own places: `_civex/exports` in the project, or `_exports` inside a drive. The **Made** tab of the **Exports** page (reached from **Files → Manage exports…**, or `civex files exports`) lists them with where they are and what space they use, and removes them:

```bash
civex files exports list
civex files exports remove archive/tables       # one, as listed: where/name
civex files exports remove --older-than 30      # anything not updated in a month
civex files exports remove --all
```

Removing a linked folder gives back no space and never touches the stored files. Removing a copied folder gives back its space. Anything of your own that you put inside an export folder is left, with the folder. Exports on a drive that isn't connected are listed once it is plugged in again.

## Where files are, and moving them

The record list, on a collection's **Records** tab and a record's
**Contains** tab, has a switch above it: **Records | Their files**. *Their
files* lists the files of exactly the records you are looking at, and of
everything beneath them, under the same filters and saved view. For example,
filter to Recordings that have a Selection with `selection_number` below 5,
then switch to their files.

Each row is one file as it is stored. A file is stored once however many
records use it, so a file three records use is one row, and every count and
size is of real files on disk. The **Record** column shows where the file sits
("Encounter 7 › Recording 2 › Selection 11"). **Used by N records** opens every
record that uses it, with the records above each, including those outside
this list. Deleted records still keep a file while they can be restored, but
they don't count as using it: the list says how many there are, apart. Inside
a record, its own files are listed with those of what it contains, so the
count matches the record's storage line. The search box at the top searches the files (their names and the
names of the records they sit under), **Kinds of file** narrows to some file
fields, and **Used by** to files that so many records use. Each record names a
file by its own name template: when they differ, the row says what else it is
called.

Above the files is a bar of where all of them are: each drive, a drive that
isn't plugged in, **not on this computer** (for a project that syncs:
downloading it fetches it from the server) and **missing**. Click a place to
list only its files. The whole view is in the page address, so it can be
bookmarked or shared.

Tick files (ticking a whole page offers every file that matches, on every
page), then:

- **Move to drive…** moves just those files onto one drive, in the background.
  Files not on this computer are downloaded straight onto it, and files on a
  drive that isn't plugged in stay where they are. A file is stored once
  however many records use it, so moving it moves it for all of them ("Used
  by 4 records (3 not listed)" says when others use it); they keep using it,
  on its new drive. A file on the home drive of a collection that uses it is
  copied instead, so that drive keeps it; the dialog says how many before
  anything moves.
- **Download to this computer** fetches the ones not on this computer from
  the server. Any the server hasn't got yet (the device that added them
  hasn't sent them) are named.
- **Free up space…** removes this computer's copies of files the server holds
  (see [Files on this computer](sync.md#which-files-this-computer-keeps)).

Each action says first what it will do, and runs as a job in the status bar.
From a terminal, the same selection options pick the same files, with `--on`
for a place and `--name` for a name:

```bash
civex files list --in Humpbacks --on field-ssd
civex files gather --in Humpbacks --on field-ssd --to archive
civex files fetch --under <record id>
civex files free --in Humpbacks --name ".wav"
```

## Downloading files

In the UI, each file field shows a download link next to the filename. Via the API:

```
GET /api/files/<sha256>
```


!!! note "On a project that syncs"
    A file another device added is downloaded from the authority the first time it
    is opened or exported, and in the background unless this computer keeps only
    the files it opens. See [Files](sync.md#files) in the sync guide.

## Restricting accepted files

File fields support two restrictions, added the same way as any other field restriction — see [Schemas & fields](schemas-and-fields.md#adding-fields):

```bash
# Only allow specific extensions
civex schema add-field recording audio --type file --accept ".wav,.flac,.mp3"

# Reject files over 100 MB
civex schema add-field document attachment --type file --max-size 104857600
```

The `--accept` value uses the same format as the HTML `accept` attribute. Extension checks are case-insensitive.

Both restrictions are enforced when a record is **saved**, not when a file is uploaded. Neither the CLI's file storage nor the web UI's `POST /api/files` upload endpoint checks `accept` or `max_size` — a file that violates either uploads successfully but is rejected when you try to attach its reference to the field.

## Backing up files

The `_civex/objects/` directory contains all file data. Include it in your backups alongside `civex.db`.

`civex dump` does not include file attachments — only schemas, collections, records, and workflows. Back up `_civex/objects/` separately.
