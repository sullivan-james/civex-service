# Files

## How file storage works

Civex uses a content-addressed object store: when you attach a file to a record, the file's bytes are stored in `_civex/objects/<sha256[:2]>/<sha256[2:]>` — the same layout as Git's object store. The record stores a lightweight reference: `{sha256, filename, size}`.

This means:
- **Identical files are stored once.** Attaching the same file to ten records uses disk space once.
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

A home only decides where **new** files are written. Deduplication always wins: a file whose content is already stored on any volume is reused where it lives and is never copied to the home — including when the only copy is on a volume that is currently unplugged. Two collections with different homes that attach the same file therefore share one stored copy.

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

## Downloading files

In the UI, each file field shows a download link next to the filename. Via the API:

```
GET /api/files/<sha256>
```

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

The `_civex/objects/` directory contains all file data. Include it in your backups alongside `civex.db`. If you use [remote sync](remote-sync.md) (`civex push`), objects are transferred automatically.

`civex dump` does not include file attachments — only schemas, collections, records, and workflows. Back up `_civex/objects/` separately, or use remote sync, which transfers objects automatically.
