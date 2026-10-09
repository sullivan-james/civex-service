# Put files on another drive

**Goal:** keep a collection's files on an external or network drive, move the
files already stored there, and later retire a drive without losing anything.

You need: a project with files in it, and the drive mounted (plugged in, or a
network share your OS has already mounted; civex doesn't mount shares).

## 1. Add the drive as a volume

```bash
civex store add archive --path /media/archive/civex --allocated-gb 500
```

```text
Added volume 'archive' at /media/archive/civex.
  Allocation: 500.0 GB
  Add it to the write queue with: civex store queue, or give a collection this volume as its home
with civex store place set.
```

**In the app:** Settings → Storage → Volumes → **Add volume**. **Browse…** lists
the folders and mounted drives of the computer running civex, and checks the
folder before you add it.

civex writes a small `.civex-volume` marker into the folder, so the drive is
recognised wherever it is mounted, and a different drive at the same path is
never written to.

## 2. Send a collection's new files there

```bash
civex store place set humpbacks archive
```

```text
New files for 'humpbacks' now go to 'archive' (spill when it is unavailable).
```

*Spill* means that if the drive is unplugged, uploads go to the next volume in
the write queue instead of failing. To refuse uploads instead, so the
collection's files are never written anywhere else:

```bash
civex store place set humpbacks archive --on-unavailable fail
```

**In the app:** Settings → Storage → **Collections**, and pick the home on the
collection's row (or tick several collections to set them together).

## 3. Move the files already stored

Preview first:

```bash
civex store move --collection humpbacks --to archive --dry-run
```

```text
Would move 2 files (391 KB); 0 already on a target.
  → archive: about 2 files (391 KB), 2.7 GB free
```

Then run it:

```bash
civex store move --collection humpbacks --to archive
```

```text
Queued 4635f033. Ctrl+C pauses; resume with `civex store transfers resume 4635f033`.
Moving 4635f033  2/2 files  14 MB/s ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
4635f033 consolidate  completed  2/2 files, 391 KB of 391 KB
```

Each file is copied, checked against its hash, and only then removed from where
it was, so stopping at any point (Ctrl+C, a power cut) loses nothing.
`civex store transfers resume <id>` carries on from where it stopped.

**In the app:** Settings → Storage → Tasks → **Move files…**. A running move
shows in the status bar on every page, with **Pause**.

## 4. Check where the files are

```bash
civex store collections
```

```text
humpbacks  2 files, 391 KB
  archive: 2 files, 391 KB
```

For one record:

```bash
civex store where bfcdc007
```

```text
Field  File       Stored on  State
audio  take1.wav  archive    online
```

## When the drive is unplugged

Nothing breaks. Records stay editable, and only the files on that drive are
unavailable. Their chip in the app says which drive to plug in. New uploads
spill to the write queue (unless the home is set to `fail`). Plug the drive back
in and everything is available again, with nothing to run.

`civex store list` shows each volume's status, and below the table why a
volume can't be used and what to do:

| Status | Meaning | What to do |
|---|---|---|
| `ok` | Readable and writable | — |
| `⚠ low space` | Near its allocation or the disk is nearly full | Move files off, or raise `--allocated-gb` with `civex store update` |
| `offline` | The path isn't there, or a network drive stopped answering | Plug in or remount the drive |
| `wrong drive` | Something else is mounted at the path | Mount the right drive. If it *is* the right one (re-formatted, marker deleted), run `civex store adopt archive` |
| `read-only` / `retired` | Readable, never written to | Set on purpose with `civex store set-state` |

## Retire an old drive

Move everything off it, then remove it:

```bash
civex store add new-archive --path /media/new-archive/civex
civex store move --off archive --to new-archive
civex store set-state archive retired
civex store place clear humpbacks        # or point it at the new drive
civex store remove archive
```

While a drive is being emptied it is made read-only, so new files don't land on
it. It goes back to its previous state when the move stops. `civex store remove`
only removes the volume from civex's settings and never deletes anything on the
drive.

## Use a drive for every new file

The write queue is the order volumes are tried for files whose collection has no
home:

```bash
civex store queue new-archive default
```

```text
Write queue set to: new-archive → default
```

## Free space taken by unused files

Files stay stored after nothing uses them any more (a record was permanently
deleted, a file was replaced). Clean-up removes them. It is a dry run unless you
pass `--apply`:

```bash
civex store gc                          # what would go, on every volume
civex store gc --volume archive --apply # delete it, on one volume
```

Files used by a record, including one you can still restore, or by a workflow
run are never removed. Files added in the last 14 days are kept too
(`--grace-days`). **In the app:** Settings → Storage → Tasks → **Clean up…**.

## See also

- [Storage volumes](../guides/storage.md): how copies, homes and moves work in detail.
- [`civex store` reference](../reference/cli/store.md).
