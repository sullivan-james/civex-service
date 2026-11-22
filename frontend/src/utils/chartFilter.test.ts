import { describe, expect, it } from 'vitest'
import { filterForChart, litBars, toggleBar } from './chartFilter'
import type { FilterTreeWire } from './filterTree'

const site = { field: 'site', schema_name: 'sample' }
const depth = { field: 'depth', schema_name: 'sample' }
const is = (value: string): FilterTreeWire => ({
  field: 'site',
  schema: 'sample',
  op: 'eq',
  value,
})
const blank: FilterTreeWire = {
  or: [
    { field: 'site', schema: 'sample', op: 'is_null' },
    { field: 'site', schema: 'sample', op: 'eq', value: '' },
  ],
}
const step = (from: number): FilterTreeWire => ({
  and: [
    { field: 'depth', schema: 'sample', op: 'gte', value: from },
    { field: 'depth', schema: 'sample', op: 'lt', value: from + 5 },
  ],
})

describe('clicking a bar', () => {
  it('adds its value, then a second as "is any of", and takes one out again', () => {
    const one = toggleBar(null, is('north'), site, 'sample')
    expect(one).toEqual(is('north'))
    const two = toggleBar(one, is('south'), site, 'sample')
    expect(two).toEqual({
      field: 'site',
      schema: 'sample',
      op: 'in',
      value: ['north', 'south'],
    })
    expect(toggleBar(two, is('north'), site, 'sample')).toEqual(is('south'))
    expect(toggleBar(one, is('north'), site, 'sample')).toBeNull()
  })

  it('keeps the rest of the filter and ANDs charts of other fields', () => {
    const tree = toggleBar(is('north'), step(5), depth, 'sample')
    expect(tree).toEqual({ and: [is('north'), step(5)] })
    const more = toggleBar(tree, step(10), depth, 'sample')
    expect(more).toEqual({ and: [is('north'), { or: [step(5), step(10)] }] })
    expect(toggleBar(more, step(5), depth, 'sample')).toEqual({
      and: [is('north'), step(10)],
    })
  })

  it('never adds the same range twice: a lone range is the whole filter', () => {
    // An AND of "from" and "under" reads as two terms when it is all there is.
    const one = toggleBar(null, step(5), depth, 'sample')
    expect(one).toEqual(step(5))
    expect(litBars(one, depth, 'sample')!(step(5))).toBe(true)
    expect(filterForChart(one, depth, 'sample')).toBeNull()
    expect(toggleBar(one, step(5), depth, 'sample')).toBeNull()
    // A second range joins it as one term, and comes out again.
    const two = toggleBar(one, step(10), depth, 'sample')
    expect(two).toEqual({ or: [step(5), step(10)] })
    expect(toggleBar(two, step(10), depth, 'sample')).toEqual(step(5))
  })

  it('treats the empty bar as one choice', () => {
    const tree = toggleBar(is('north'), blank, site, 'sample')
    const lit = litBars(tree, site, 'sample')!
    expect(lit(blank)).toBe(true)
    expect(lit(is('north'))).toBe(true)
    expect(toggleBar(tree, blank, site, 'sample')).toEqual(is('north'))
  })

  it('reads a condition written in the builder without its kind', () => {
    const written: FilterTreeWire = { field: 'site', op: 'eq', value: 'north' }
    expect(litBars(written, site, 'sample')!(is('north'))).toBe(true)
    expect(toggleBar(written, is('north'), site, 'sample')).toBeNull()
  })
})

describe('a chart and its own field', () => {
  it('counts without the simple condition on its field, lighting the chosen bars', () => {
    const tree: FilterTreeWire = { and: [is('north'), step(5)] }
    expect(filterForChart(tree, site, 'sample')).toEqual(step(5))
    expect(filterForChart(tree, depth, 'sample')).toEqual(is('north'))
    const lit = litBars(tree, site, 'sample')!
    expect(lit(is('north'))).toBe(true)
    expect(lit(is('south'))).toBe(false)
  })

  it('leaves a tree it cannot show exactly as written, with nothing lit', () => {
    const mixed: FilterTreeWire = {
      or: [
        is('north'),
        { field: 'depth', schema: 'sample', op: 'gt', value: 3 },
      ],
    }
    const not: FilterTreeWire = {
      field: 'site',
      schema: 'sample',
      op: 'ne',
      value: 'north',
    }
    const twice: FilterTreeWire = { and: [is('north'), is('south')] }
    for (const tree of [mixed, not, twice]) {
      expect(filterForChart(tree, site, 'sample')).toEqual(tree)
      expect(litBars(tree, site, 'sample')).toBeNull()
    }
    // A click then narrows further; it never rewrites what was there.
    expect(toggleBar(not, is('south'), site, 'sample')).toEqual({
      and: [not, is('south')],
    })
  })
})
