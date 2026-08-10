/**
 * Hand-rolled YAML generation for the guided import's "save as automation"
 * escape hatch. Only ever emits the two fixed shapes below (a files-input
 * workflow around `civex.create_records_from_files` /
 * `civex.match_files_to_records`, or a record-triggered CSV workflow around
 * `civex.load_file` -> `civex.load_csv` -> `civex.rows_to_records`) so a
 * full YAML emitter would be overkill — `JSON.stringify` on every scalar
 * keeps each line valid YAML (YAML flow scalars accept JSON string syntax)
 * without hand-writing escaping rules.
 */

function str(v: string): string {
  return JSON.stringify(v)
}

export interface FilesImportAutomationParams {
  name: string
  description?: string
  strategy: 'create' | 'match'
  schemaName: string
  fileField: string
  datasetName: string
  /** Child-schema imports attach to one fixed parent record regardless of
   * which record the automation is later manually re-run against. */
  parentRecordId?: string
  keyField?: string
  pattern?: string
}

export function buildFilesImportWorkflowYaml(
  p: FilesImportAutomationParams,
): string {
  const plugin =
    p.strategy === 'match'
      ? 'civex.match_files_to_records'
      : 'civex.create_records_from_files'
  const lines: string[] = [`name: ${str(p.name)}`]
  if (p.description) lines.push(`description: ${str(p.description)}`)
  lines.push(
    'inputs:',
    '  files:',
    '    type: files',
    'steps:',
    '  - id: import',
    `    plugin: ${plugin}`,
    '    inputs:',
    '      files: __input__.files',
    '    config:',
    `      schema: ${str(p.schemaName)}`,
    `      file_field: ${str(p.fileField)}`,
    `      dataset: ${str(p.datasetName)}`,
  )
  if (p.strategy === 'match') {
    lines.push(
      `      key_field: ${str(p.keyField ?? '')}`,
      `      pattern: ${str(p.pattern ?? '')}`,
      `      parent_record_id: ${str(p.parentRecordId ?? '')}`,
    )
  } else if (p.parentRecordId) {
    lines.push(`      context_record_id: ${str(p.parentRecordId)}`)
  }
  return lines.join('\n') + '\n'
}

export interface CsvImportAutomationParams {
  name: string
  description?: string
  /** The "import batch" schema whose file field triggers this workflow. */
  triggerSchemaName: string
  csvFieldName: string
  targetSchemaName: string
  datasetName: string
  /** CSV column -> target field name. */
  fieldMapping: Record<string, string>
}

export function buildCsvImportWorkflowYaml(
  p: CsvImportAutomationParams,
): string {
  const lines: string[] = [`name: ${str(p.name)}`]
  if (p.description) lines.push(`description: ${str(p.description)}`)
  lines.push(
    `record_schema: ${str(p.triggerSchemaName)}`,
    'triggers:',
    '  record_created:',
    `    schema: ${str(p.triggerSchemaName)}`,
    'steps:',
    '  - id: load',
    '    plugin: civex.load_file',
    '    config:',
    `      field: ${str(p.csvFieldName)}`,
    '  - id: parse',
    '    plugin: civex.load_csv',
    '    inputs:',
    '      bytes: load.bytes',
    '  - id: create',
    '    plugin: civex.rows_to_records',
    '    inputs:',
    '      table: parse.table',
    '    config:',
    `      schema: ${str(p.targetSchemaName)}`,
    `      dataset: ${str(p.datasetName)}`,
  )
  const mapping = Object.entries(p.fieldMapping)
  if (mapping.length > 0) {
    lines.push('      field_mapping:')
    for (const [col, field] of mapping) {
      lines.push(`        ${str(col)}: ${str(field)}`)
    }
  }
  return lines.join('\n') + '\n'
}
