import { describe, it, expect } from 'vitest'
import {
  conditionLabel,
  describeTree,
  referenceIdsIn,
  topLevelTerms,
  withoutTerm,
} from './filterLabels'
import type { FilterTreeWire } from './filterTree'
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

describe('reference labels', () => {
  const ref = {
    id: 'f',
    name: 'patient_ref',
    label: null,
    type: 'reference',
    required: false,
    restrictions: {},
    default: null,
    position: 0,
    sourceSchemaName: 'visit',
    relation: 'self',
  } as unknown as FilterableField
  const id = 'abcdef12-0000-0000-0000-000000000000'

  it('swaps a reference id for the record name, or its short id until known', () => {
    const cond = { field: 'patient_ref', op: 'eq', value: id } as const
    expect(conditionLabel(cond, [ref], 'visit', { [id]: 'Ada' })).toBe(
      'Patient Ref is Ada',
    )
    expect(conditionLabel(cond, [ref], 'visit')).toBe('Patient Ref is abcdef12')
  })

  it('collects the ids of reference conditions only, through nested groups', () => {
    const text = { ...ref, name: 'note', type: 'string' } as FilterableField
    const wire: FilterTreeWire = {
      and: [
        { field: 'patient_ref', op: 'in', value: [id, 'other'] },
        { or: [{ field: 'note', op: 'eq', value: 'not-an-id' }] },
      ],
    }
    expect(referenceIdsIn(wire, [ref, text])).toEqual([id, 'other'])
    expect(referenceIdsIn(null, [ref])).toEqual([])
  })
})
