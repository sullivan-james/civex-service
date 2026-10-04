import { describe, it, expect } from 'vitest'
import { describeAuditEntry } from './schemaAudit'
import type { AuditLogEntry } from '../api/audit'

function makeEntry(overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    id: 'audit-1',
    commit_id: null,
    action: 'create',
    entity_type: 'schema',
    entity_id: 'schema-1',
    old_data: null,
    new_data: null,
    changes: [],
    now: null,
    timestamp: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('describeAuditEntry — schema', () => {
  it('describes a create', () => {
    const summary = describeAuditEntry(
      makeEntry({ action: 'create', new_data: { name: 'trial' } }),
    )
    expect(summary.title).toBe('Schema "trial" created')
    expect(summary.detail).toBeNull()
  })

  it('describes a rename', () => {
    const summary = describeAuditEntry(
      makeEntry({
        action: 'update',
        old_data: { name: 'trial', label: null, description: null },
        new_data: { name: 'trials', label: null, description: null },
      }),
    )
    expect(summary.title).toBe('Schema "trials" updated')
    expect(summary.detail).toContain('renamed "trial" → "trials"')
  })

  it('describes a delete, noting the cascade', () => {
    const summary = describeAuditEntry(
      makeEntry({ action: 'delete', old_data: { name: 'trial' } }),
    )
    expect(summary.title).toBe('Schema "trial" deleted')
    expect(summary.detail).toContain('every record typed by it')
  })
})

describe('describeAuditEntry — field', () => {
  it('describes a field addition with its type', () => {
    const summary = describeAuditEntry(
      makeEntry({
        entity_type: 'field',
        action: 'create',
        new_data: { name: 'age', dtype: 'integer' },
      }),
    )
    expect(summary.title).toBe('Field "age" added')
    expect(summary.detail).toBe('Type: integer')
  })

  it('describes a restriction change', () => {
    const summary = describeAuditEntry(
      makeEntry({
        entity_type: 'field',
        action: 'update',
        old_data: { name: 'age', dtype: 'integer', restrictions: {} },
        new_data: {
          name: 'age',
          dtype: 'integer',
          restrictions: { min: 0, max: 100 },
        },
      }),
    )
    expect(summary.title).toBe('Field "age" updated')
    expect(summary.detail).toContain('restrictions (none) → min 0 · max 100')
  })

  it('describes a required change', () => {
    const summary = describeAuditEntry(
      makeEntry({
        entity_type: 'field',
        action: 'update',
        old_data: { name: 'age', required: false },
        new_data: { name: 'age', required: true },
      }),
    )
    expect(summary.detail).toContain('made required')
  })

  it('describes a field removal', () => {
    const summary = describeAuditEntry(
      makeEntry({
        entity_type: 'field',
        action: 'delete',
        old_data: { name: 'age' },
      }),
    )
    expect(summary.title).toBe('Field "age" removed')
  })
})
