import { describe, expect, it } from 'vitest'
import type { AuditLogEntry } from '../api/audit'
import { auditEntryTarget, describeAnyAuditEntry } from './activityAudit'

const entry = (over: Partial<AuditLogEntry>): AuditLogEntry =>
  ({
    id: 'a1',
    entity_type: 'view',
    entity_id: 'v1',
    action: 'create',
    old_data: null,
    new_data: null,
    ...over,
  }) as AuditLogEntry

describe('Activity on saved filters and the Analytics page', () => {
  it('calls a saved view a saved filter', () => {
    expect(
      describeAnyAuditEntry(entry({ new_data: { name: 'QC' } })).title,
    ).toBe('Saved filter “QC” created')
  })

  it('says the page was edited and links to it', () => {
    const e = entry({ entity_type: 'dashboard', action: 'update' })
    expect(describeAnyAuditEntry(e).title).toBe('Analytics page edited')
    expect(auditEntryTarget(e)).toEqual({
      to: '/analytics',
      label: 'Analytics',
    })
  })
})
