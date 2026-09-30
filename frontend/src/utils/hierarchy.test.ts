import { describe, it, expect } from 'vitest'
import {
  ancestorSchemas,
  defaultColumnNames,
  fieldKey,
  filterableFields,
  isDescendantSchema,
  relatedSchemaNames,
  schemaLevels,
  schemasById,
} from './hierarchy'
import type { Schema } from '../api/schemas'

function schema(
  name: string,
  parent: Schema | null,
  fields: [string, string][] = [],
): Schema {
  return {
    id: `id-${name}`,
    name,
    label: null,
    description: null,
    parent_id: parent?.id ?? null,
    display_fields: [],
    deleted_at: null,
    fields: fields.map(([n, type]) => ({
      id: `${name}-${n}`,
      name: n,
      label: null,
      type,
      required: false,
      restrictions: {},
      default: null,
      position: null,
    })),
  }
}

const encounter = schema('encounter', null, [['site', 'string']])
const recording = schema('recording', encounter, [['rate', 'integer']])
const selection = schema('selection', recording, [
  ['selection_table', 'string'],
  ['audio', 'file'],
])
const photo = schema('photo', encounter, [['file', 'file']])
const unrelated = schema('unrelated', null, [['x', 'string']])
const all = [selection, unrelated, photo, recording, encounter]
const byId = schemasById(all)

describe('hierarchy', () => {
  it('lists ancestors nearest first', () => {
    expect(ancestorSchemas(selection, byId).map((s) => s.name)).toEqual([
      'recording',
      'encounter',
    ])
    expect(ancestorSchemas(encounter, byId)).toEqual([])
  })

  it('orders levels parents-first, siblings by name', () => {
    expect(schemaLevels(all).map((l) => [l.schema.name, l.depth])).toEqual([
      ['encounter', 0],
      ['photo', 1],
      ['recording', 1],
      ['selection', 2],
      ['unrelated', 0],
    ])
  })

  it('lists only the levels below a root, excluding it', () => {
    expect(
      schemaLevels(all, encounter).map((l) => [l.schema.name, l.depth]),
    ).toEqual([
      ['photo', 0],
      ['recording', 0],
      ['selection', 1],
    ])
  })

  it('knows what descends from what', () => {
    expect(isDescendantSchema(selection, encounter, byId)).toBe(true)
    expect(isDescendantSchema(encounter, selection, byId)).toBe(false)
    expect(isDescendantSchema(photo, recording, byId)).toBe(false)
  })

  it('offers own, ancestor then descendant fields to filter on', () => {
    const fields = filterableFields(recording, all)
    expect(fields.map((f) => `${f.relation}:${fieldKey(f)}`)).toEqual([
      'self:recording::rate',
      'ancestor:encounter::site',
      'descendant:selection::selection_table',
      'descendant:selection::audio',
    ])
  })

  it('relates a schema to its ancestors and descendants only', () => {
    expect([...relatedSchemaNames(recording, all)].sort()).toEqual([
      'encounter',
      'recording',
      'selection',
    ])
  })

  it('defaults to own columns, bar files', () => {
    expect(defaultColumnNames(selection)).toEqual(['selection_table'])
    expect(defaultColumnNames(photo)).toEqual([])
  })
})
