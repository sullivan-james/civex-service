/**
 * Hand-rolled YAML generation for the guided import's "save as automation"
 * escape hatch. Only ever emits the two fixed shapes below (a files-input
 * workflow of a Files step and `civex.save_records`, or a record-triggered CSV
 * workflow of a `civex.table` step and `civex.save_records`) so a
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
  const lines: string[] = [`name: ${str(p.name)}`]
  if (p.description) lines.push(`description: ${str(p.description)}`)
  lines.push(
    'steps:',
    '  - id: files',
    '    plugin: civex.files@1',
    '    config:',
    '      source: run',
    '  - id: import',
    '    plugin: civex.save_records@1',
    '    inputs:',
    '      files: files.files',
    '    config:',
    `      schema: ${str(p.schemaName)}`,
    `      file_field: ${str(p.fileField)}`,
    `      dataset: ${str(p.datasetName)}`,
  )
  if (p.strategy === 'match') {
    lines.push(
      '      if_exists: update',
      '      match_on:',
      `        - ${str(p.keyField ?? '')}`,
      `      filename_pattern: ${str(p.pattern ?? '')}`,
      `      parent_record_id: ${str(p.parentRecordId ?? '')}`,
    )
  } else {
    lines.push('      if_exists: add_new')
    if (p.parentRecordId)
      lines.push(`      parent_record_id: ${str(p.parentRecordId)}`)
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
    '  - id: parse',
    '    plugin: civex.table@1',
    '    config:',
    `      field: ${str(p.csvFieldName)}`,
    '  - id: create',
    '    plugin: civex.save_records@1',
    '    inputs:',
    '      rows: parse.table',
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
