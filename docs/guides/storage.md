# Storage volumes

Where civex keeps files, and how they move between drives. For the step-by-step
version, see [Put files on another drive](../how-to/storage-drives.md).

## The object store

A file's bytes are stored once per drive, named by their SHA-256 hash, in the
same layout as Git:

```text
_civex/objects/
  3f/9c01ab…e2          ← the bytes of one file, no name or extension
  manifest.jsonl        ← {"sha256", "filename", "size"} per file, for humans
```

A record holds a small reference, `{sha256, filename, size}`. So:

- **The same content is stored once** per drive, however many records use it.
- **Stored files never change.** Editing means attaching a new file.
- **`manifest.jsonl`** says what each blob originally was, so a bare copy of a
  volume is readable even without civex.

## Volumes

A **volume** is a folder that holds objects, usually on its own drive. Every
project starts with `default` (`_civex/objects`). Volumes are defined in
`_civex/config.toml`; the database only records which files are on which
volume.

```toml
[store]
volume_queue = ["new-archive", "default"]

[store.volumes.new-archive]
path = "/media/new-archive/civex"
allocated_gb = 500.0
id = "6c1f…"            # matches the .civex-volume marker on the drive
```

| Command | Does |
|---|---|
| `civex store list` | Each volume's status, space and place in the queue |
| `civex store add <name> --path P [--allocated-gb N] [--queue]` | Add a folder as a volume |
| `civex store update <name> --path P` | The drive is now mounted somewhere else |
| `civex store queue A B …` | Order tried for new files with no home |
| `civex store set-state <name> active\|readonly\|retired` | Stop writing to it |
| `civex store adopt <name>` | "This *is* that drive" (marker lost or drive re-formatted) |
| `civex store remove <name>` | Forget it. Nothing on the drive is deleted |

**Identity.** `civex store add` writes a `.civex-volume` marker into the folder.
A drive is recognised wherever it is mounted, and a different drive (or an empty
mount point) at the same path is reported as `wrong drive` and never written
to. civex never creates a missing volume folder outside the project, because an
unmounted drive's path would otherwise be recreated on the wrong disk.

**Network drives** work when your OS has mounted them (an NFS or SMB share under
`/mnt` or `/Volumes`, a mapped drive letter, a UNC path). civex doesn't mount
shares or hold credentials. A share that stops answering is reported `offline`
within a few seconds, and work on other volumes carries on.

**Adding a volume checks it first**: whether the folder exists or will be made,
is writable, has room, is a separate disk from the project, or already belongs to
another volume. The app's **Add volume** form shows the same checks as you type.

## Where new files go

1. The collection's **home** volume, if it has one and the home can take the file.
2. Otherwise the **write queue**, in order, skipping volumes that can't take it.

```bash
civex store place set humpbacks archive                       # home
civex store place set humpbacks archive --on-unavailable fail # never anywhere else
civex store place list
civex store place clear humpbacks
```

Homes are keyed by collection id in `config.toml`
(`[store.placement.<id>]`), so renaming a collection changes nothing. Setting
or clearing a home moves no existing files.

Content already on any drive is reused, not written again. The one exception: a
collection's home gets its own copy of content it doesn't hold yet.

## Copies and what records point at

The same content can be on several drives. **Each record's file points at
exactly one copy.** That makes "where are this collection's files" a fact, not
a guess:

- `civex store collections` and Settings → Storage count each collection on the
  copies its live records point at.
- A copy that records from several collections point at is counted once, under
  **Shared by several collections**, so a drive's rows add up to what it holds.
- `civex store where <record>` lists a record's files and the drive each is on;
  `--details` adds paths on disk and what else uses each file.

Where a file is stored belongs to this computer. It isn't part of the record and
doesn't sync.

## Moving files

| Move | CLI | What moves |
|---|---|---|
| Empty a drive | `civex store move --off old --to archive` | Everything on `old` |
| Gather a collection | `civex store move --collection humpbacks --to archive` | What its live records point at |
| Gather a selection | `civex files gather --in humpbacks --on field-ssd --to archive` | Just those files |

All three work the same way:

- **A move repoints.** The records it covers point at the target. A file is
  copied there unless the target already has that content, in which case nothing
  is copied. The old copy is removed once nothing points at it. If records the
  move doesn't cover still use it, it stays (*copied, not moved*). The preview
  says how many files are copied, how many are already there, and what space is
  freed.
- **It can't lose files.** Each file is copied to a scratch file, checked against
  its hash, renamed into place, recorded, and *then* removed from the source.
  Stopping at any point leaves each file in its old place, its new place, or both.
- **One at a time.** A second move waits its turn (`civex store transfers list`).
  `Ctrl+C` in the terminal pauses. `civex store transfers resume <id>` carries on,
  and `pause`/`cancel` work from another terminal or the app.
- **A drive being emptied is made read-only** until the move stops (finished,
  paused, cancelled or failed), so new files don't land on it.
- **Problems don't stop the rest.** A damaged or missing file is listed and left.
  A full target moves on to the next `--to` and pauses when there is none. A
  drive that stops answering pauses the move, and a move started in the app
  resumes by itself when the drive is back.

## Cleaning up

`civex store gc` removes copies nothing points at. It is a dry run without
`--apply`.

```bash
civex store gc
```

```text
Scanned 2 object(s) in the store.
  2 referenced by a live record or job
  0 unreferenced but within the 14-day grace period
  Collectible 0 object(s), 0 B
```

Kept: anything a record uses (including deleted records you can still restore),
anything a workflow run uses, and anything newer than `--grace-days` (14). Not
kept: files only old history mentions, so an old Activity entry may name a file
that's gone. `--volume` limits it to one drive. It can't run during a move.

## In the app

**Settings → Storage** has three tabs, and above them a list of anything needing
attention (an unplugged drive holding files, low space, an interrupted move).

| Tab | For |
|---|---|
| **Volumes** | Each drive's status and space. A drive's name opens its own page: which collections are on it, unused files, moves involving it |
| **Collections** | Each collection's files by drive, its home, **Gather**, and what this computer keeps when syncing |
| **Tasks** | **Move files…**, **Clean up…**, and the list of moves |

On records, a file on a drive that can't be reached is always marked, and its
chip says which drive to plug in. With more than one volume, every file shows a
chip with its drive. **Settings → Advanced → Show advanced options** adds full
details: every copy, its path on disk, its hash, and what else uses it.
