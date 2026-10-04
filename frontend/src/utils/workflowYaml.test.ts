import { describe, it, expect } from 'vitest'
import {
  buildFilesImportWorkflowYaml,
  buildCsvImportWorkflowYaml,
} from './workflowYaml'

describe('buildFilesImportWorkflowYaml', () => {
  it('emits a create_records_from_files step for the "create" strategy', () => {
    const yaml = buildFilesImportWorkflowYaml({
      name: 'Import scans',
      strategy: 'create',
      schemaName: 'scan',
      fileField: 'file',
      datasetName: 'study-1',
    })
    expect(yaml).toContain('name: "Import scans"')
    expect(yaml).toContain('type: files')
    expect(yaml).toContain('plugin: civex.create_records_from_files')
    expect(yaml).toContain('files: __input__.files')
    expect(yaml).toContain('schema: "scan"')
    expect(yaml).toContain('file_field: "file"')
    expect(yaml).toContain('dataset: "study-1"')
    expect(yaml).not.toContain('context_record_id')
    expect(yaml).not.toContain('key_field')
  })

  it('includes context_record_id only when a parent record is given', () => {
    const yaml = buildFilesImportWorkflowYaml({
      name: 'Import scans',
      strategy: 'create',
      schemaName: 'scan',
      fileField: 'file',
      datasetName: 'study-1',
      parentRecordId: 'abc-123',
    })
    expect(yaml).toContain('context_record_id: "abc-123"')
  })

  it('emits a match_files_to_records step with key/pattern for the "match" strategy', () => {
    const yaml = buildFilesImportWorkflowYaml({
      name: 'Attach scans',
      strategy: 'match',
      schemaName: 'scan',
      fileField: 'file',
      datasetName: 'study-1',
      parentRecordId: 'parent-1',
      keyField: 'subject_id',
      pattern: 'subject_(\\d+)',
    })
    expect(yaml).toContain('plugin: civex.match_files_to_records')
    expect(yaml).toContain('key_field: "subject_id"')
    expect(yaml).toContain('pattern: "subject_(\\\\d+)"')
    expect(yaml).toContain('parent_record_id: "parent-1"')
  })
})

describe('buildCsvImportWorkflowYaml', () => {
  it('emits a record_created-triggered load_file -> parse_table -> rows_to_records chain', () => {
    const yaml = buildCsvImportWorkflowYaml({
      name: 'Import subjects',
      triggerSchemaName: 'subject_import',
      csvFieldName: 'csv_file',
      targetSchemaName: 'subject',
      datasetName: 'study-1',
      fieldMapping: { 'Subject ID': 'subject_id', Age: 'age' },
    })
    expect(yaml).toContain('record_schema: "subject_import"')
    expect(yaml).toContain('record_created:')
    expect(yaml).toContain('schema: "subject_import"')
    expect(yaml).toContain('plugin: civex.load_file')
    expect(yaml).toContain('field: "csv_file"')
    expect(yaml).toContain('plugin: civex.parse_table')
    expect(yaml).toContain('bytes: load.bytes')
    expect(yaml).toContain('plugin: civex.rows_to_records')
    expect(yaml).toContain('table: parse.table')
    expect(yaml).toContain('schema: "subject"')
    expect(yaml).toContain('dataset: "study-1"')
    expect(yaml).toContain('"Subject ID": "subject_id"')
    expect(yaml).toContain('"Age": "age"')
  })

  it('omits field_mapping entirely when no columns are mapped', () => {
    const yaml = buildCsvImportWorkflowYaml({
      name: 'Import subjects',
      triggerSchemaName: 'subject_import',
      csvFieldName: 'csv_file',
      targetSchemaName: 'subject',
      datasetName: 'study-1',
      fieldMapping: {},
    })
    expect(yaml).not.toContain('field_mapping')
  })
})
