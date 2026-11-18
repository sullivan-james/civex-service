import { describe, expect, it } from 'vitest'
import { parse } from 'yaml'
import { newStepId, readDraft, stemFor, writeDraft } from './workflowModel'

const HAND_WRITTEN = `# Made by hand
name: Calculate stats
description: >
  When a contour file is uploaded.
record_schema: Selection
triggers:
  record_updated:
    schema: Selection
    fields: [contour_file]
steps:
  - id: load
    plugin: civex.load_file
    timeout: 30 # seconds
    config:
      field: contour_file

  - id: parse
    plugin: civex.parse_table
    config:
      delimiter: ","
    inputs:
      bytes: load.bytes
`

function draftOf(content: string) {
  const r = readDraft(content)
  if (!r.ok) throw new Error(r.problem)
  return r.draft
}

describe('readDraft', () => {
  it('reads what the form shows', () => {
    const d = draftOf(HAND_WRITTEN)
    expect(d.name).toBe('Calculate stats')
    expect(d.enabled).toBe(true)
    expect(d.schema).toBe('Selection')
    expect(d.onUpdated).toBe(true)
    expect(d.onCreated).toBe(false)
    expect(d.watchFields).toEqual(['contour_file'])
    expect(d.steps.map((s) => s.id)).toEqual(['load', 'parse'])
    expect(d.steps[1].inputs).toEqual({ bytes: 'load.bytes' })
  })

  it('takes the schema from the trigger when record_schema is missing', () => {
    const d = draftOf(
      'name: x\ntriggers:\n  record_created:\n    schema: doc\nsteps: []\n',
    )
    expect(d.schema).toBe('doc')
    expect(d.onCreated).toBe(true)
  })

  it('says why it cannot show broken YAML', () => {
    const r = readDraft('name: [unclosed')
    expect(r.ok).toBe(false)
  })
})

describe('writeDraft', () => {
  it('changes nothing when nothing changed', () => {
    expect(writeDraft(HAND_WRITTEN, draftOf(HAND_WRITTEN))).toBe(HAND_WRITTEN)
  })

  it('keeps comments and keys the form does not own', () => {
    const d = draftOf(HAND_WRITTEN)
    d.steps[1].config = { delimiter: 'tab' }
    d.enabled = false
    const out = writeDraft(HAND_WRITTEN, d)
    expect(out).toContain('# Made by hand')
    expect(out).toContain('timeout: 30 # seconds')
    expect(out).toContain('delimiter: tab')
    expect(parse(out).enabled).toBe(false)
  })

  it('reorders, removes and adds steps', () => {
    const d = draftOf(HAND_WRITTEN)
    d.steps = [
      d.steps[1],
      {
        id: 'save',
        plugin: 'civex.save_fields',
        config: {},
        inputs: { updates: 'parse.table' },
        condition: '',
      },
    ]
    const wf = parse(writeDraft(HAND_WRITTEN, d))
    expect(wf.steps.map((s: { id: string }) => s.id)).toEqual(['parse', 'save'])
    expect(wf.steps[1]).toEqual({
      id: 'save',
      plugin: 'civex.save_fields',
      inputs: { updates: 'parse.table' },
    })
  })

  it('writes triggers from the schema and drops them when none is on', () => {
    const d = draftOf(HAND_WRITTEN)
    d.onCreated = true
    d.watchFields = []
    let wf = parse(writeDraft(HAND_WRITTEN, d))
    expect(wf.triggers).toEqual({
      record_updated: { schema: 'Selection' },
      record_created: { schema: 'Selection' },
    })
    d.onCreated = false
    d.onUpdated = false
    wf = parse(writeDraft(HAND_WRITTEN, d))
    expect(wf.triggers).toBeUndefined()
    expect(wf.record_schema).toBe('Selection')
  })

  it('writes inputs, conditions and drops blank settings', () => {
    const d = draftOf('name: x\nsteps: []\n')
    d.inputs = [{ key: 'files', type: 'files', label: 'Contour files' }]
    d.steps = [
      {
        id: 'match',
        plugin: 'civex.match_files_to_records',
        config: { schema: 'Selection', dataset: '' },
        inputs: { files: '__input__.files' },
        condition: 'other.ok == True',
      },
    ]
    const wf = parse(writeDraft('name: x\nsteps: []\n', d))
    expect(wf.inputs).toEqual({
      files: { type: 'files', label: 'Contour files' },
    })
    expect(wf.steps[0].config).toEqual({ schema: 'Selection' })
    expect(wf.steps[0].if).toBe('other.ok == True')
  })
})

describe('names', () => {
  it('makes step ids that do not clash', () => {
    expect(newStepId('Read a file', [])).toBe('read_a_file')
    expect(newStepId('Read a file', ['read_a_file'])).toBe('read_a_file_2')
  })
  it('makes a file stem from a name', () => {
    expect(stemFor('Fill the date from the name!')).toBe(
      'fill-the-date-from-the-name',
    )
  })
})
