import { describe, expect, it } from 'vitest'
import type { AuditLogEntry } from '../api/audit'
import { auditEntryTarget, describeAnyAuditEntry } from './activityAudit'
import {
  OPEN_NOTES_FILTER,
  asksForOpenNotes,
  noteFilterFields,
  openNotesHref,
  openNotesText,
} from './notes'

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

describe('open notes in the explorer', () => {
  it('offers Has open notes as a field of the record itself', () => {
    const fields = noteFilterFields()
    expect(fields.map((f) => f.name)).toEqual([OPEN_NOTES_FILTER])
    expect(fields[0].ownerless).toBe(true)
  })

  it('links to All records filtered to open notes, and knows it there', () => {
    const href = openNotesHref()
    expect(href.startsWith('/collections?tab=records&filter=')).toBe(true)
    const filter = JSON.parse(
      new URLSearchParams(href.split('?')[1]).get('filter')!,
    )
    expect(asksForOpenNotes(filter)).toBe(true)
    expect(
      asksForOpenNotes({
        and: [{ field: 'site', op: 'eq', value: 'a' }, filter],
      }),
    ).toBe(true)
    expect(asksForOpenNotes({ or: [filter] })).toBe(false)
    expect(asksForOpenNotes({ ...filter, value: false })).toBe(false)
    expect(asksForOpenNotes(null)).toBe(false)
  })

  it('shows how many threads are open and the latest one', () => {
    expect(openNotesText(2, 'depth looks off')).toBe('2 open · depth looks off')
    expect(openNotesText(0, null)).toBeNull()
  })
})

describe('Activity on notes', () => {
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
    expect(describeAnyAuditEntry(resolved).title).toBe('Thread resolved')
  })

  it('says a reply is a reply, and resolving is of the thread', () => {
    const replied = entry({
      new_data: { body: 'fixed', record_id: 'r1', thread_id: 'n0' },
    })
    expect(describeAnyAuditEntry(replied).title).toBe('Replied to a note')
    const deleted = entry({
      action: 'delete',
      old_data: { body: 'fixed', record_id: 'r1', thread_id: 'n0' },
    })
    expect(describeAnyAuditEntry(deleted).title).toBe('Reply deleted')
  })
})
