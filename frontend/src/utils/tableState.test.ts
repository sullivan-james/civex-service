import { describe, it, expect } from 'vitest'
import { applyTablePatch, nextSort, parseTableState } from './tableState'

describe('table state in the address', () => {
  it('round-trips search, filter, sort and paging', () => {
    const filter = { field: 'status', op: 'eq' as const, value: 'failed' }
    const sp = applyTablePatch(
      new URLSearchParams(),
      {
        q: 'parse',
        filter,
        sort: [{ field: 'created_at', direction: 'desc' }],
        page: 2,
        pageSize: 10,
      },
      '',
      25,
    )
    expect(parseTableState(sp, '', 25)).toEqual({
      q: 'parse',
      filter,
      sort: [{ field: 'created_at', direction: 'desc' }],
      page: 2,
      pageSize: 10,
    })
  })

  it('keeps two tables and other parameters apart', () => {
    let sp = new URLSearchParams('tab=runs')
    sp = applyTablePatch(sp, { q: 'a' }, 'runs.')
    sp = applyTablePatch(sp, { q: 'b' }, 'history.')
    expect(sp.get('tab')).toBe('runs')
    expect(parseTableState(sp, 'runs.').q).toBe('a')
    expect(parseTableState(sp, 'history.').q).toBe('b')
  })

  it('sends the table back to page one when what matches changes', () => {
    const sp = applyTablePatch(new URLSearchParams('page=4'), { q: 'x' })
    expect(parseTableState(sp).page).toBe(0)
    const kept = applyTablePatch(new URLSearchParams('page=4'), { page: 5 })
    expect(parseTableState(kept).page).toBe(5)
  })

  it('cycles a column ascending, descending, off', () => {
    const asc = nextSort([], 'status')
    const desc = nextSort(asc, 'status')
    expect(desc).toEqual([{ field: 'status', direction: 'desc' }])
    expect(nextSort(desc, 'status')).toEqual([])
    expect(nextSort(desc, 'trigger')).toEqual([
      { field: 'trigger', direction: 'asc' },
    ])
  })
})
