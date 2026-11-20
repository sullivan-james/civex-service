import { describe, expect, it } from 'vitest'
import {
  compareSummaryCells,
  splitGroupKey,
  splitKeys,
  withCondition,
} from './summary'

describe('summary address and helpers', () => {
  it('reads the written forms', () => {
    expect(splitKeys('site.region,taken:month,')).toEqual([
      'site.region',
      'taken:month',
    ])
    expect(splitKeys(null)).toEqual([])
    expect(splitGroupKey('site.region')).toEqual({
      field: 'site.region',
      how: '',
    })
    expect(splitGroupKey('depth:2.5')).toEqual({ field: 'depth', how: '2.5' })
  })

  it("adds a group's condition to the filter", () => {
    const where = { field: 'a', op: 'eq' as const, value: 1 }
    expect(withCondition(null, where)).toEqual(where)
    const filter = { field: 'b', op: 'eq' as const, value: 2 }
    expect(withCondition(filter, where)).toEqual({ and: [filter, where] })
  })

  it('sorts blanks last and numbers as numbers', () => {
    const cells = [10, null, 9, 100]
    expect([...cells].sort(compareSummaryCells)).toEqual([9, 10, 100, null])
    expect(['b10', 'b9'].sort(compareSummaryCells)).toEqual(['b9', 'b10'])
  })
})
