import { describe, it, expect } from 'vitest'
import { collectFields, joinableColumns } from './viewFields'
import type { Schema } from '../api/schemas'

function field(name: string, type = 'string', restrictions = {}) {
  return {
    id: `${name}-id`,
    name,
    label: null,
    type,
    required: false,
    restrictions,
    default: null,
    position: null,
  }
}

function schema(overrides: Partial<Schema>): Schema {
  return {
    id: `${overrides.name}-schema-id`,
    name: 'schema',
    label: null,
    description: null,
    parent_id: null,
    display_fields: [],
    fields: [],
    deleted_at: null,
    ...overrides,
  }
}

describe('collectFields', () => {
  it('returns own fields when there is no parent', () => {
    const s = schema({ name: 'trial', fields: [field('subject')] })
    const byId = new Map([[s.id, s]])
    expect(collectFields(s, byId).map((f) => f.name)).toEqual(['subject'])
  })

  it('appends inherited fields after own fields, own field wins on name clash', () => {
    const parent = schema({
      name: 'base',
      fields: [field('site'), field('subject')],
    })
    const child = schema({
      name: 'child',
      parent_id: parent.id,
      fields: [field('subject', 'integer')],
    })
    const byId = new Map([
      [parent.id, parent],
      [child.id, child],
    ])
    const resolved = collectFields(child, byId)
    expect(resolved.map((f) => f.name)).toEqual(['subject', 'site'])
    expect(resolved[0].type).toBe('integer')
    expect(resolved[0].sourceSchemaName).toBe('child')
    expect(resolved[1].sourceSchemaName).toBe('base')
  })
})

describe('joinableColumns', () => {
  it('lists target-schema fields reachable through a reference field', () => {
    const customer = schema({
      name: 'customer',
      fields: [field('email'), field('region')],
    })
    const invoice = schema({
      name: 'invoice',
      fields: [
        field('amount', 'integer'),
        field('customer', 'reference', { schema: 'customer' }),
      ],
    })
    const byId = new Map([
      [customer.id, customer],
      [invoice.id, invoice],
    ])
    const byName = new Map([
      ['customer', customer],
      ['invoice', invoice],
    ])
    const columns = joinableColumns(invoice, byId, byName)
    expect(columns.map((c) => c.value)).toEqual([
      'customer.email',
      'customer.region',
    ])
  })

  it('skips reference fields with no target schema restriction', () => {
    const invoice = schema({
      name: 'invoice',
      fields: [field('customer', 'reference')],
    })
    const byId = new Map([[invoice.id, invoice]])
    const byName = new Map([['invoice', invoice]])
    expect(joinableColumns(invoice, byId, byName)).toEqual([])
  })
})
