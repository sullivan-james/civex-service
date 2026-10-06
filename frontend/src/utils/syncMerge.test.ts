import { describe, expect, it } from 'vitest'
import type { SyncConflict } from '../api/remote'
import { buildMerge } from './syncMerge'

const FIELDS = [
  { id: 'f1', name: 'site' },
  { id: 'f2', name: 'depth' },
]

function c(id: string, extra: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id,
    kind: 'conflict',
    entity_id: 'r1',
    field: 'data.f1',
    field_label: 'Site',
    dtype: 'string',
    theirs: 'theirs',
    yours: 'mine',
    base: 'was',
    status: 'open',
    resolution: null,
    record_name: 'Dive',
    created_at: `2026-10-05T10:00:0${id}Z`,
    changes: [],
    ...extra,
  } as SyncConflict
}

describe('buildMerge', () => {
  it('lays clashes out as rows, theirs on the left and yours on the right', () => {
    const m = buildMerge([c('1')], FIELDS)
    expect(m.sections).toHaveLength(1)
    const row = m.sections[0].rows[0]
    expect([row.fieldName, row.left, row.right, row.base]).toEqual([
      'site',
      'theirs',
      'mine',
      'was',
    ])
    expect(m.open).toBe(1)
  })

  it('shows a refused change as before and after, a section of its own', () => {
    const refused = c('2', {
      kind: 'rejected',
      field: null,
      attempted: 'update',
      changes: [
        {
          field_id: 'f2',
          field_name: 'depth',
          field_label: 'Depth',
          dtype: 'float',
          before: 1,
          after: 9,
          current: 9,
        },
      ],
    })
    const m = buildMerge([c('1'), refused], FIELDS)
    expect(m.sections.map((s) => s.kind)).toEqual(['clashes', 'attempt'])
    const row = m.sections[1].rows[0]
    expect([row.fieldName, row.left, row.right]).toEqual(['depth', 1, 9])
  })

  it('keeps a clash on a removed field, with no field to edit', () => {
    const m = buildMerge([c('1', { field: 'data.gone' })], FIELDS)
    expect(m.sections[0].rows[0].fieldName).toBeNull()
  })

  it('remembers how one was settled, and counts only the open ones', () => {
    const m = buildMerge(
      [c('1', { status: 'resolved', resolution: 'theirs' }), c('2')],
      FIELDS,
    )
    expect(m.sections[0].rows.map((r) => r.settled)).toEqual(['theirs', null])
    expect([m.open, m.total]).toEqual([1, 2])
  })
})
