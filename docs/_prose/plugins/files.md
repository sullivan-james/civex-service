# `civex.files@1`  (Files)

Bring files into a workflow. **Where the files come from** (`source`) is one of:

- **Chosen when the workflow is run** (`run`): whoever runs it drops files in, or
  points at a folder on this computer. This replaces the old workflow-level
  `inputs: {x: {type: files}}`. The step's `id` names it in the run dialog, the
  command line (`--input <id>=*.wav`) and the API; **What to ask for** (`label`)
  is what the person sees.
- **A folder on this computer** (`folder`): the files of `folder` that match `glob`
  (`*.wav`), optionally with `subfolders`. The computer running civex reads them
  itself, so **nothing is uploaded** and a run shows how far it has got. Files
  whose content is already stored are not copied again, so reading the same
  folder twice is quick. Hidden files (names starting with a dot) are skipped.
  A server that hosts other people's projects does not offer this
  (`server_path_import` is a feature of a computer's own civex, off on a hub).
- **A field of this record** (`field`): the file, or files, in a file or file-list
  field of the record the workflow runs on.

<!-- civex:tables -->

```yaml
- id: wavs
  plugin: civex.files@1
  config:
    source: run
    label: Sequence WAV files

- id: put
  plugin: civex.save_records@1
  config:
    schema: sequence_selection
    match_on: [selection_number]
    filename_pattern: 'sel_(\d+)'
    file_field: seq_wav_file
  inputs:
    files: wavs.files
```
