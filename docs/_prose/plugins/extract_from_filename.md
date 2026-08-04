# `civex.extract_from_filename`

Apply a regex to a file field's filename (or a plain string field) and optionally convert the captured value to a typed output. Reach for this when the data you need — a timestamp, a selection number, a session ID — is embedded in a filename rather than stored as its own field. Works with `file`, `file_list`, and `string` fields.

<!-- civex:tables -->

**`date_format` tokens**

| Token | Matches | Example |
|---|---|---|
| `YYYY` | 4-digit year | `2024` |
| `MM` | 2-digit month | `03` |
| `DD` | 2-digit day | `15` |
| `HH` | 2-digit hour (24h) | `09` |
| `mm` | 2-digit minute | `30` |
| `SS` | 2-digit second | `00` |

All other characters in the format string are treated as **raw regex fragments** — not strftime codes. This lets you use `[-_]` to match either a dash or underscore as a separator:

```
YYYYMMDD[-_]HHmmSS   →  matches  20240315-093000  and  20240315_093000
```

Extracted datetimes are stored as UTC ISO 8601 strings.

**Examples**

Extract a datetime from `20210218_075000_recording.wav`:
```yaml
- id: extract_time
  plugin: civex.extract_from_filename
  config:
    field: audio_file
    pattern: '(\d{8}[-_]\d{6})'
    output_type: datetime
    date_format: 'YYYYMMDD[-_]HHmmSS'
```

Extract a selection number from `sel_042_contour.csv`:
```yaml
- id: extract_num
  plugin: civex.extract_from_filename
  config:
    field: contour_file
    pattern: 'sel_(\d+)'
    output_type: integer
```
