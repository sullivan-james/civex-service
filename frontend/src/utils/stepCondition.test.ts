import { describe, expect, it } from 'vitest'
import { readCondition, writeCondition } from './stepCondition'

describe('step conditions', () => {
  it.each([
    ['load.ok', { ref: 'load.ok', op: 'set', value: '' }],
    ['not load.ok', { ref: 'load.ok', op: 'unset', value: '' }],
    ['parse.rows > 0', { ref: 'parse.rows', op: '>', value: '0' }],
    ["get.value == 'x y'", { ref: 'get.value', op: '==', value: 'x y' }],
  ])('reads %s', (expr, want) => {
    expect(readCondition(expr)).toEqual(want)
  })

  it('leaves what is not one test alone', () => {
    expect(readCondition('a.b and c.d')).toBeNull()
    expect(readCondition('a.b == c.d')).toBeNull()
  })

  it('writes Python literals', () => {
    expect(writeCondition({ ref: 'a.b', op: '==', value: 'yes' })).toBe(
      'a.b == "yes"',
    )
    expect(writeCondition({ ref: 'a.b', op: '!=', value: 'true' })).toBe(
      'a.b != True',
    )
    expect(writeCondition({ ref: 'a.b', op: '>', value: '2.5' })).toBe(
      'a.b > 2.5',
    )
    expect(writeCondition({ ref: 'a.b', op: 'unset', value: '' })).toBe(
      'not a.b',
    )
  })
})
