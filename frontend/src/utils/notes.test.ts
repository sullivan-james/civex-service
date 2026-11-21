import { describe, expect, it } from 'vitest'
import type { AuditEvent, AuditLogEntry } from '../api/audit'
import {
  auditEntryTarget,
  describeAnyAuditEntry,
  describeAuditEvent,
} from './activityAudit'
import {
  OPEN_NOTES_FILTER,
  REVIEW_FILTER,
  reviewFilterFields,
  reviewStatus,
} from './review'

const entry = (over: Partial<AuditLogEntry>): AuditLogEntry =>
  ({
    id: 'a1',
    entity_type: 'note',
    entity_id: 'n1',
    action: 'create',
    old_data: null,
    new_data: null,
    changes: [],
    ...over,
  }) as AuditLogEntry

describe('review in the filter', () => {
  it('offers the status and open notes as fields of the record itself', () => {
    const fields = reviewFilterFields()
    expect(fields.map((f) => f.name)).toEqual([
      REVIEW_FILTER,
      OPEN_NOTES_FILTER,
    ])
    expect(fields.every((f) => f.ownerless)).toBe(true)
    expect(fields[0].restrictions).toEqual({
      choices: ['none', 'needs_check', 'checked'],
    })
  })

  it('reads a record without a review as not reviewed', () => {
    expect(reviewStatus(null)).toBe('none')
    expect(reviewStatus({ status: 'checked', by: 'ana', at: '' })).toBe(
      'checked',
    )
  })
})

describe('Activity on notes and reviews', () => {
  it('says what happened to a note, with what it says, and links to its record', () => {
    const added = entry({
      new_data: { body: 'depth looks off', record_id: 'r1' },
    })
    expect(describeAnyAuditEntry(added)).toEqual({
      title: 'Note added',
      detail: '“depth looks off”',
    })
    expect(auditEntryTarget(added)).toEqual({
      to: '/records/r1?tab=notes',
      label: 'Record',
    })
    const resolved = entry({
      action: 'update',
      new_data: { record_id: 'r1' },
      changes: [
        {
          field: 'resolved_at',
          label: null,
          dtype: null,
          before: null,
          after: '2026-11-21T10:00:00+00:00',
        },
      ],
    })
    expect(describeAnyAuditEntry(resolved).title).toBe('Note resolved')
  })

  it('titles a record’s review in words', () => {
    const marked = entry({
      entity_type: 'record',
      action: 'update',
      changes: [
        {
          field: '@review',
          label: 'Review',
          dtype: 'string',
          before: 'Not reviewed',
          after: 'Needs a check',
        },
      ],
    })
    expect(describeAnyAuditEntry(marked).title).toBe('Marked as needs a check')
  })

  it('says how many records a review marked', () => {
    const event = {
      kind: 'batch',
      entry: null,
      batch: { id: 'b', kind: 'review', label: 'Checked' },
      parts: [{ entity_type: 'record', action: 'update', count: 12 }],
    } as unknown as AuditEvent
    expect(describeAuditEvent(event).title).toBe('Marked 12 records as checked')
  })
})
