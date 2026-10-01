import { describe, expect, it } from 'vitest'
import { atLeast, isValidPartialDate, precisionOf } from './partialDates'

describe('partial dates', () => {
  it('knows the precision of a value', () => {
    expect(precisionOf('2019')).toBe('year')
    expect(precisionOf('2019-06')).toBe('month')
    expect(precisionOf('2019-06-14')).toBe('day')
    expect(precisionOf('June 2019')).toBeNull()
  })

  it('rejects impossible dates', () => {
    expect(isValidPartialDate('2023-02-30')).toBe(false)
    expect(isValidPartialDate('2023-13')).toBe(false)
    expect(isValidPartialDate('2024-02-29')).toBe(true)
    expect(isValidPartialDate('2023-02-29')).toBe(false)
  })

  it('checks against the least precise allowed', () => {
    expect(atLeast('2019', 'year')).toBe(true)
    expect(atLeast('2019', 'month')).toBe(false)
    expect(atLeast('2019-06', 'month')).toBe(true)
    expect(atLeast('2019-06', 'day')).toBe(false)
  })
})
