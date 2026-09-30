import { describe, it, expect } from 'vitest'
import {
  applyExplorerPatch,
  parseExplorerState,
  sameFilter,
  schemaRecordsPath,
  selectionMatchesView,
  viewPatch,
} from './explorerState'
import type { View } from '../api/views'

const params = (q: string) => new URLSearchParams(q)

describe('explorer URL state', () => {
  it('reads defaults from an empty querystring', () => {
    expect(parseExplorerState(params(''))).toEqual({
      schema: null,
      within: null,
      q: '',
      filter: null,
      sort: [],
      cols: null,
      view: null,
      page: 0,
      pageSize: 50,
    })
  })

  it('round-trips everything it writes', () => {
    const tree = { field: 'age', op: 'gte' as const, value: 3, schema: 'x' }
    const out = applyExplorerPatch(params(''), {
      schema: 'selection',
      within: 'abc',
      q: 'S02',
      filter: tree,
      sort: [{ field: 'age', direction: 'desc' }],
      cols: ['a', 'b'],
      view: 'v',
      page: 2,
      pageSize: 100,
    })
    expect(parseExplorerState(out)).toEqual({
      schema: 'selection',
      within: 'abc',
      q: 'S02',
      filter: tree,
      sort: [{ field: 'age', direction: 'desc' }],
      cols: ['a', 'b'],
      view: 'v',
      page: 2,
      pageSize: 100,
    })
  })

  it('leaves defaults out of the URL', () => {
    const out = applyExplorerPatch(params('q=x&page=3'), { q: '', page: 0 })
    expect(out.toString()).toBe('')
  })

  it('goes back to page 1 when what is listed changes, not when paging', () => {
    const base = params('page=4&schema=a')
    expect(applyExplorerPatch(base, { q: 'x' }).get('page')).toBeNull()
    expect(applyExplorerPatch(base, { schema: 'b' }).get('page')).toBeNull()
    expect(applyExplorerPatch(base, { page: 5 }).get('page')).toBe('6')
  })

  it("leaves other params alone (a host page's own)", () => {
    const out = applyExplorerPatch(params('tab=runs'), { q: 'x' })
    expect(out.get('tab')).toBe('runs')
    expect(out.get('q')).toBe('x')
  })

  it('ignores a malformed filter or page', () => {
    const s = parseExplorerState(params('filter=%7Bnope&page=-2&size=abc'))
    expect(s.filter).toBeNull()
    expect(s.page).toBe(0)
    expect(s.pageSize).toBe(50)
  })
})

describe('sameFilter', () => {
  it('ignores key order', () => {
    expect(
      sameFilter(
        { field: 'a', op: 'eq', value: 1 },
        { value: 1, op: 'eq', field: 'a' },
      ),
    ).toBe(true)
    expect(sameFilter(null, { field: 'a', op: 'eq', value: 1 })).toBe(false)
  })
})

describe('saved views', () => {
  const view: View = {
    id: 'v1',
    schema_id: 's',
    schema_name: 'selection',
    name: 'missing',
    columns: [],
    filter_tree: { field: 't', op: 'is_null', value: true },
    sort: [{ field: 'begin', direction: 'asc' }],
  }

  it('applying a view stands for its filter, sort and columns', () => {
    expect(viewPatch(view)).toEqual({
      view: 'missing',
      filter: view.filter_tree,
      sort: view.sort,
      cols: null,
    })
  })

  it('is unmodified until the selection diverges', () => {
    const applied = { ...parseExplorerState(params('')), ...viewPatch(view) }
    expect(selectionMatchesView(applied, view, ['a', 'b'])).toBe(true)
    expect(
      selectionMatchesView({ ...applied, cols: ['a'] }, view, ['a', 'b']),
    ).toBe(false)
    expect(selectionMatchesView({ ...applied, filter: null }, view, [])).toBe(
      false,
    )
  })

  it('treats no saved columns as the default columns', () => {
    const applied = { ...parseExplorerState(params('')), ...viewPatch(view) }
    expect(
      selectionMatchesView({ ...applied, cols: ['a', 'b'] }, view, ['a', 'b']),
    ).toBe(true)
  })
})

describe('schemaRecordsPath', () => {
  it('opens a schema, optionally on a view', () => {
    expect(schemaRecordsPath('s1')).toBe('/schemas/s1/records')
    expect(schemaRecordsPath('s1', 'my view')).toBe(
      '/schemas/s1/records?view=my%20view',
    )
  })
})
