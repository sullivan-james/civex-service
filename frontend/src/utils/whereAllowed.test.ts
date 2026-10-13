import { describe, expect, it } from 'vitest'
import { whereAllowed } from './permissions'

describe('where an action is allowed, in words', () => {
  const names = new Map([
    ['c1', 'Field season'],
    ['c2', 'Archive'],
  ])
  it('is everywhere, or the collections by name', () => {
    expect(whereAllowed(['project'], names)).toBe('Everywhere in this project')
    expect(whereAllowed(['collection:c1'], names)).toBe('In Field season')
    expect(whereAllowed(['collection:c1', 'collection:c2'], names)).toBe(
      'In Field season and Archive',
    )
  })
})
