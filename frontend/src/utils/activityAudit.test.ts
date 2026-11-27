import { describe, expect, it } from 'vitest'
import type { AuditEvent, AuditLogEntry } from '../api/audit'
import {
  auditEntryTarget,
  describeAnyAuditEntry,
  describeAuditEvent,
} from './activityAudit'

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

describe('describeAuditEvent already done', () => {
  const event = (done: NonNullable<AuditEvent['already_done']> | null) =>
    ({
      id: 'b1',
      kind: 'batch',
      timestamp: '2026-01-01T00:00:00Z',
      count: 12,
      entry: null,
      batch: { id: 'b1', kind: 'delete', label: null, ref: null },
      parts: [{ entity_type: 'record', action: 'delete', count: 12 }],
      already_done: done,
    }) as unknown as AuditEvent

  it('says how many were already deleted, and by whom', () => {
    const s = describeAuditEvent(event({ count: 8, by: ['jamie'] }))
    expect(s.title).toBe('Deleted 12 records')
    expect(s.detail).toBe('8 already deleted on the server by jamie')
  })

  it('says nothing when none were', () => {
    expect(describeAuditEvent(event(null)).detail).toBeNull()
  })

  it('says another of your devices when it was the same person', () => {
    const s = describeAuditEvent(
      event({ count: 3, by: [], own: 3, own_devices: ['laptop'] }),
    )
    expect(s.detail).toBe(
      '3 already deleted on the server from another of your devices (laptop)',
    )
  })

  it('reads a single change as a plain statement', () => {
    const single = {
      ...event({ count: 1, by: ['jamie'] }),
      kind: 'entry',
      batch: null,
      entry: {
        id: 'e',
        entity_type: 'record',
        action: 'delete',
        entity_id: 'r',
        changes: [],
        old_data: null,
        new_data: null,
      },
    } as unknown as AuditEvent
    expect(describeAuditEvent(single).detail).toContain(
      'Already deleted on the server by jamie',
    )
  })
})
