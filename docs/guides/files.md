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

A volume is recognised by an identity, not by its path. `civex store add` writes a small `.civex-volume` marker (a random id) into the volume and records the same id beside the volume's path in `_civex/config.toml`. A drive is therefore recognised wherever it is mounted, and a different drive mounted at the same path is reported as the wrong drive instead of being written to. Nothing is written to a volume that fails this check, and Civex never creates a missing volume directory on its own — an unmounted drive's path would otherwise be recreated on the wrong disk. (Volumes inside the project, such as the default `_civex/objects`, are always trusted.)

If a volume is reported as the wrong drive but this is in fact the right one — the marker was deleted, or the drive was re-formatted — run `civex store adopt <name>` to rewrite the marker. A volume added before identities existed has none and is checked by path alone until you adopt it.

Uploads skip a volume that isn't usable and go to the next one in the write queue; if none can take the file, the upload fails with the reason for each volume.

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
    On a new record's form, file fields show a file picker, and the files are attached when you save the form. On an existing record's detail page, a picked file is uploaded and then **waits for approval** beside the field: it shows its name, size and whether it passes the field's `accept` and `max_size` rules, and nothing on the record changes until you click **Approve** (or **Discard**). Workflows that watch the field run on approval, not on upload. Pending files live in the page, so leaving it discards them; the uploaded bytes stay in the object store until garbage collection removes them. Multiple files can be attached to a `file_list` field, and a batch is approved together.

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
