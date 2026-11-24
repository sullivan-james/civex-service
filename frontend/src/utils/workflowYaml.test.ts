import { describe, it, expect } from 'vitest'
import {
  buildFilesImportWorkflowYaml,
  buildCsvImportWorkflowYaml,
} from './workflowYaml'

describe('buildFilesImportWorkflowYaml', () => {
  it('emits a Files step and a save_records step that adds new records for the "create" strategy', () => {
    const yaml = buildFilesImportWorkflowYaml({
      name: 'Import scans',
      strategy: 'create',
      schemaName: 'scan',
      fileField: 'file',
      datasetName: 'study-1',
    })
    expect(yaml).toContain('name: "Import scans"')
    expect(yaml).toContain('plugin: civex.files@1')
    expect(yaml).toContain('source: run')
    expect(yaml).toContain('plugin: civex.save_records@1')
    expect(yaml).toContain('files: files.files')
    expect(yaml).toContain('if_exists: add_new')
    expect(yaml).toContain('schema: "scan"')
    expect(yaml).toContain('file_field: "file"')
    expect(yaml).toContain('dataset: "study-1"')
    expect(yaml).not.toContain('parent_record_id')
    expect(yaml).not.toContain('match_on')
  })

  it('includes parent_record_id only when a parent record is given', () => {
    const yaml = buildFilesImportWorkflowYaml({
      name: 'Import scans',
      strategy: 'create',
      schemaName: 'scan',
      fileField: 'file',
      datasetName: 'study-1',
      parentRecordId: 'abc-123',
    })
    expect(yaml).toContain('parent_record_id: "abc-123"')
  })

  it('emits match_on and filename_pattern for the "match" strategy', () => {
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
    expect(yaml).toContain('if_exists: update')
    expect(yaml).toContain('- "subject_id"')
    expect(yaml).toContain('filename_pattern: "subject_(\\\\d+)"')
    expect(yaml).toContain('parent_record_id: "parent-1"')
  })
})

describe('buildCsvImportWorkflowYaml', () => {
  it('emits a record_created-triggered table -> save_records chain', () => {
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
    expect(yaml).toContain('plugin: civex.table@1')
    expect(yaml).toContain('field: "csv_file"')
    expect(yaml).toContain('plugin: civex.save_records@1')
    expect(yaml).toContain('rows: parse.table')
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
