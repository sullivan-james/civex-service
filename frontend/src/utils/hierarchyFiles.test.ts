import { describe, it, expect } from 'vitest'
import type { Schema } from '../api/schemas'
import { schemaTreeHasFiles, viewHasFileColumns } from './hierarchy'

const field = (name: string, type: string) => ({
  id: name,
  name,
  label: null,
  type,
  required: false,
  restrictions: {},
  default: null,
  position: null,
})
const schema = (
  id: string,
  parent: string | null,
  fields: [string, string][],
): Schema => ({
  id,
  name: id,
  label: null,
  description: null,
  parent_id: parent,
  display_template: null,
  fields: fields.map(([n, t]) => field(n, t)),
  deleted_at: null,
})

// Encounter -> Recording -> Selection: the files are on the Selections.
const encounter = schema('encounter', null, [['site', 'string']])
const recording = schema('recording', 'encounter', [['rate', 'integer']])
const selection = schema('selection', 'recording', [
  ['table', 'file'],
  ['extras', 'file_list'],
])
const all = [encounter, recording, selection]

describe('schemaTreeHasFiles', () => {
  it('is true for an Encounter, whose Selections hold the files', () => {
    expect(schemaTreeHasFiles(encounter, all)).toBe(true)
    expect(schemaTreeHasFiles(recording, all)).toBe(true)
  })

  it('is true for the schema that holds them', () => {
    expect(schemaTreeHasFiles(selection, all)).toBe(true)
  })

  it('counts a file field inherited from above', () => {
    const parent = schema('parent', null, [['scan', 'file']])
    const child = schema('child', 'parent', [['note', 'string']])

    expect(schemaTreeHasFiles(child, [parent, child])).toBe(true)
  })

  it('is false where nothing in the tree can hold a file', () => {
    const lonely = schema('lonely', null, [['name', 'string']])

    expect(schemaTreeHasFiles(lonely, [...all, lonely])).toBe(false)
  })

  it('ignores a branch that is not beneath it', () => {
    const other = schema('other', null, [['name', 'string']])
    const filesElsewhere = schema('elsewhere', null, [['f', 'file']])

    expect(schemaTreeHasFiles(other, [other, filesElsewhere])).toBe(false)
  })
})

describe('viewHasFileColumns', () => {
  it('needs a file column among the view’s columns', () => {
    expect(
      viewHasFileColumns({ schema_id: 'selection', columns: ['table'] }, all),
    ).toBe(true)
    expect(
      viewHasFileColumns({ schema_id: 'selection', columns: ['extras'] }, all),
    ).toBe(true)
  })

  it('is false when the file fields are not shown', () => {
    expect(
      viewHasFileColumns({ schema_id: 'selection', columns: ['site'] }, all),
    ).toBe(false)
    expect(
      viewHasFileColumns({ schema_id: 'selection', columns: [] }, all),
    ).toBe(false)
  })

  it('knows an inherited file column', () => {
    const parent = schema('parent', null, [['scan', 'file']])
    const child = schema('child', 'parent', [])

    expect(
      viewHasFileColumns({ schema_id: 'child', columns: ['scan'] }, [
        parent,
        child,
      ]),
    ).toBe(true)
  })

  it('is false for a view of a schema that is gone', () => {
    expect(
      viewHasFileColumns({ schema_id: 'nope', columns: ['table'] }, all),
    ).toBe(false)
  })
})
