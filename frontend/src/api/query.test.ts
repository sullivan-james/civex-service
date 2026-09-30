import { describe, it, expect } from 'vitest'
import { decodeSort, encodeSort, recordQueryString } from './query'

describe('recordQueryString', () => {
  it('is empty when there is nothing to send', () => {
    expect(recordQueryString(undefined)).toBe('')
    expect(recordQueryString({ schema: null, within: null })).toBe('')
  })

  it('serialises the whole selection', () => {
    const qs = recordQueryString({
      schema: 'selection',
      within: 'rec-1',
      search: 'S02',
      filter: { field: 'selection_table', op: 'is_null', value: true },
      sort: [{ field: 'site', schema: 'encounter', direction: 'desc' }],
      columns: ['site'],
      child_counts: true,
      limit: 25,
      offset: 50,
    })
    const p = new URLSearchParams(qs)
    expect(p.get('schema')).toBe('selection')
    expect(p.get('within')).toBe('rec-1')
    expect(p.get('search')).toBe('S02')
    expect(JSON.parse(p.get('filter')!)).toEqual({
      field: 'selection_table',
      op: 'is_null',
      value: true,
    })
    expect(p.getAll('sort')).toEqual(['encounter.site:desc'])
    expect(p.getAll('columns')).toEqual(['site'])
    expect(p.get('child_counts')).toBe('true')
    expect(p.get('limit')).toBe('25')
    expect(p.get('offset')).toBe('50')
  })
})

describe('sort encoding', () => {
  it('round-trips, with and without a schema', () => {
    for (const s of [
      { field: 'age', direction: 'asc' as const },
      { field: 'site', schema: 'encounter', direction: 'desc' as const },
    ]) {
      expect(decodeSort(encodeSort(s))).toEqual(s)
    }
  })

  it('defaults to ascending and rejects junk', () => {
    expect(decodeSort('age')).toEqual({ field: 'age', direction: 'asc' })
    expect(decodeSort('age:sideways')).toBeNull()
    expect(decodeSort(':asc')).toBeNull()
  })
})
