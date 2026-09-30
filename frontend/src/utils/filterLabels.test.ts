import { describe, it, expect } from 'vitest'
import {
  conditionLabel,
  describeTree,
  topLevelTerms,
  withoutTerm,
} from './filterLabels'
import type { FilterableField } from './hierarchy'

function field(
  name: string,
  owner: string,
  relation: FilterableField['relation'],
  label: string | null = null,
): FilterableField {
  return {
    id: `${owner}-${name}`,
    name,
    label,
    type: 'string',
    required: false,
    restrictions: {},
    default: null,
    position: null,
    sourceSchemaName: owner,
    relation,
  }
}

const fields = [
  field('status', 'recording', 'self'),
  field('site', 'encounter', 'ancestor', 'Site name'),
  field('selection_table', 'selection', 'descendant'),
]

describe('conditionLabel', () => {
  it('leaves out the schema when it is the one listed', () => {
    expect(
      conditionLabel(
        { schema: 'recording', field: 'status', op: 'eq', value: 'open' },
        fields,
        'recording',
      ),
    ).toBe('Status is open')
  })

  it('names another schema, and uses the field label', () => {
    expect(
      conditionLabel(
        { schema: 'encounter', field: 'site', op: 'eq', value: 'Georges' },
        fields,
        'recording',
      ),
    ).toBe('Encounter · Site name is Georges')
  })

  it('reads an empty check and a list', () => {
    expect(
      conditionLabel(
        { schema: 'selection', field: 'selection_table', op: 'is_null' },
        fields,
        'recording',
      ),
    ).toBe('Selection · Selection Table is empty')
    expect(
      conditionLabel(
        { field: 'status', op: 'in', value: ['a', 'b'] },
        fields,
        'recording',
      ),
    ).toBe('Status is any of a, b')
  })
})

describe('terms', () => {
  const a = { field: 'a', op: 'eq' as const, value: 1 }
  const b = { field: 'b', op: 'eq' as const, value: 2 }
  const c = { field: 'c', op: 'eq' as const, value: 3 }

  it('splits an AND into chips and keeps an OR as one', () => {
    expect(topLevelTerms({ and: [a, b] })).toEqual([a, b])
    expect(topLevelTerms({ or: [a, b] })).toEqual([{ or: [a, b] }])
    expect(topLevelTerms(a)).toEqual([a])
    expect(topLevelTerms(null)).toEqual([])
  })

  it('removes one chip, collapsing what is left', () => {
    expect(withoutTerm({ and: [a, b, c] }, 1)).toEqual({ and: [a, c] })
    expect(withoutTerm({ and: [a, b] }, 0)).toEqual(b)
    expect(withoutTerm(a, 0)).toBeNull()
  })

  it('describes a nested group in brackets', () => {
    expect(describeTree({ or: [a, b] }, [], 'x')).toBe('(a is 1 or b is 2)')
  })
})
