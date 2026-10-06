import { describe, expect, it } from 'vitest'
import type { SyncConflict } from '../api/remote'
import {
  describeAttempt,
  inReviewOrder,
  kindLabel,
  layoutConflicts,
  takeLabel,
} from './syncConflicts'

function c(id: string, extra: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id,
    kind: 'conflict',
    entity_type: 'record',
    entity_id: 'r1',
    field: 'data.f1',
    record_name: 'Dive',
    created_at: `2026-10-05T10:00:0${id}Z`,
    changes: [],
    ...extra,
  } as SyncConflict
}

const FIELDS = [
  { id: 'f1', name: 'site' },
  { id: 'f2', name: 'depth' },
]

describe('layoutConflicts', () => {
  it('puts a clash under its field and marks it', () => {
    const layout = layoutConflicts([c('1')], FIELDS)
    expect(layout.clashes.get('site')?.map((x) => x.id)).toEqual(['1'])
    expect([...layout.marked]).toEqual(['site'])
    expect(layout.count).toBe(1)
  })

  it('keeps a clash whose field has gone where it can still be seen', () => {
    const layout = layoutConflicts([c('1', { field: 'data.gone' })], FIELDS)
    expect(layout.loose).toHaveLength(1)
    expect(layout.marked.size).toBe(0)
  })

  it('shows a refused change beside each field it set, and the reason on the record', () => {
    const change = (field_id: string, field_name: string) => ({
      field_id,
      field_name,
      field_label: field_name,
      dtype: 'string',
      before: null,
      after: 'x',
      current: 'x',
    })
    const refused = c('1', {
      kind: 'rejected',
      field: null,
      attempted: 'create',
      changes: [change('f1', 'site'), change('f9', 'gone')],
    })
    const layout = layoutConflicts([refused], FIELDS)
    expect(layout.recordLevel).toEqual([refused])
    expect([...layout.attempts.keys()]).toEqual(['site'])
    expect([...layout.marked]).toEqual(['site'])
  })
})

describe('inReviewOrder', () => {
  it('keeps a record together, then oldest first', () => {
    const list = [
      c('2', { record_name: 'B', entity_id: 'b' }),
      c('3', { record_name: 'A', entity_id: 'a' }),
      c('1', { record_name: 'B', entity_id: 'b' }),
    ]
    expect(inReviewOrder(list).map((x) => x.id)).toEqual(['3', '1', '2'])
  })
})

describe('a change that was not taken', () => {
  it('says it was put back as the server has it, and why', () => {
    const row = c('1', {
      kind: 'not_taken',
      entity_type: 'schema',
      field: null,
      message:
        "Part of one change that could not go in whole: The record name of 'site' would use 'code', which it no longer has",
    })
    const said = describeAttempt(row, (iso) => iso)
    expect(said).toContain('back as the server has it')
    expect(said).toContain("would use 'code'")
    expect(kindLabel('not_taken')).toBe('Not taken')
    expect(takeLabel('not_taken', 'theirs')).toBe('OK')
  })
})
