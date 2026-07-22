# Files

## How file storage works

Civex uses a content-addressed object store: when you attach a file to a record, the file's bytes are stored in `_civex/objects/<sha256[:2]>/<sha256[2:]>` — the same layout as Git's object store. The record stores a lightweight reference: `{sha256, filename, size}`.

This means:
- **Identical files are stored once.** Attaching the same file to ten records uses disk space once.
- **Files are immutable.** The SHA-256 hash is the address; the content never changes.
- **Filenames are cosmetic.** The stored filename is the original name you uploaded, but retrieval is always by hash.

## File field types

| Type | Stores |
|---|---|
| `file` | A single file attachment |
| `file_list` | Multiple file attachments |

## Attaching files via CLI

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

## Attaching files via the UI

On a record's detail page, file fields show a file picker. Multiple files can be attached to a `file_list` field. Uploaded files are stored immediately; they are associated with the record when you save the form.

## Downloading files

In the UI, each file field shows a download link next to the filename.

Via the API:

```
GET /api/files/<sha256>
```

## Restricting accepted files

File fields support two restrictions:

```bash
# Only allow specific extensions
civex schema add-field recording audio --type file --accept ".wav,.flac,.mp3"

# Reject files over 100 MB
civex schema add-field document attachment --type file --max-size 104857600
```

The `--accept` value uses the same format as the HTML `accept` attribute. Extension checks are case-insensitive.

## Backing up files

The `_civex/objects/` directory contains all file data. Include it in your backups alongside `civex.db`. If you use [remote sync](remote-sync.md) (`civex push`), objects are transferred automatically.
