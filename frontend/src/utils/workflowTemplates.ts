/**
 * The workflows "New workflow" offers to start from. Each is ordinary YAML
 * that the builder then shows: a starting point, not a separate kind of
 * workflow, so anything made from one can be changed in every way. Settings
 * the person must choose are left blank (the builder marks them), and every
 * template starts switched off, so its first run is one someone chose after
 * trying it.
 */

export interface WorkflowTemplate {
  id: string
  title: string
  description: string
  /** The YAML, for a workflow on records of `schema` ('' when not chosen). */
  build: (schema: string) => string
}

function head(name: string, schema: string): string {
  return [
    `name: ${JSON.stringify(name)}`,
    'enabled: false',
    schema ? `record_schema: ${JSON.stringify(schema)}` : null,
  ]
    .filter(Boolean)
    .join('\n')
}

function onChange(schema: string): string {
  return schema
    ? `triggers:\n  record_updated:\n    schema: ${JSON.stringify(schema)}\n`
    : ''
}

export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'blank',
    title: 'Start from nothing',
    description: 'Choose when it runs and add the steps yourself.',
    build: (schema) => `${head('New workflow', schema)}\nsteps: []\n`,
  },
  {
    id: 'from-file-name',
    title: 'Fill a field from a file’s name',
    description:
      'When a file is added, take a date, number or code out of its name and put it in a field.',
    build: (schema) => `${head('Fill a field from the file name', schema)}
${onChange(schema)}steps:
  - id: take_from_name
    plugin: civex.extract_from_filename
    config:
      field: null
  - id: set_field
    plugin: civex.save_field
    config:
      field: null
    inputs:
      value: take_from_name.value
`,
  },
  {
    id: 'copy-field',
    title: 'Copy one field into another',
    description:
      'When a field changes, put its value in another field of the same record.',
    build: (schema) => `${head('Copy a field', schema)}
${onChange(schema)}steps:
  - id: read
    plugin: civex.get_field
    config:
      field: null
  - id: set_field
    plugin: civex.save_field
    config:
      field: null
    inputs:
      value: read.value
`,
  },
  {
    id: 'match-files',
    title: 'Put files on matching records',
    description:
      'Run it with a batch of files; each goes on the record inside this one whose number or code is in its name.',
    build: (schema) => `${head('Put files on matching records', schema)}
inputs:
  files:
    type: files
    label: Files
steps:
  - id: match
    plugin: civex.match_files_to_records
    config:
      schema: null
      key_field: null
      file_field: null
      pattern: null
    inputs:
      files: __input__.files
`,
  },
  {
    id: 'record-per-file',
    title: 'Make a record for each file',
    description:
      'Run it with a batch of files; each becomes a new record inside this one.',
    build: (schema) => `${head('Make a record for each file', schema)}
inputs:
  files:
    type: files
    label: Files
steps:
  - id: make_records
    plugin: civex.create_records_from_files
    config:
      schema: null
      file_field: null
    inputs:
      files: __input__.files
`,
  },
  {
    id: 'own-plugin',
    title: 'Run one of my plugins on a file',
    description:
      'When a file is added, hand it to a plugin of yours and save what it works out on the record.',
    build: (schema) => `${head('Run my plugin on a file', schema)}
${onChange(schema)}steps:
  - id: read_file
    plugin: civex.load_file
    config:
      field: null
  - id: my_plugin
    plugin: ""
  - id: save
    plugin: civex.save_fields
`,
  },
  {
    id: 'table',
    title: 'Add or update records from a table',
    description:
      'When a CSV or similar file is added, make or update a record for each row.',
    build: (schema) => `${head('Records from a table', schema)}
${onChange(schema)}steps:
  - id: read_file
    plugin: civex.load_file
    config:
      field: null
  - id: read_table
    plugin: civex.parse_table
    inputs:
      bytes: read_file.bytes
  - id: add_or_update
    plugin: civex.upsert_records
    config:
      schema: null
      key_field: null
    inputs:
      table: read_table.table
`,
  },
]
