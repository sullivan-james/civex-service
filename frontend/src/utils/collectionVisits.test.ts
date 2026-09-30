import { describe, it, expect } from 'vitest'
import {
  readVisits,
  recordVisit,
  topCollections,
  VISITS_KEY,
} from './collectionVisits'

function memoryStorage(initial?: string) {
  let value = initial ?? null
  return {
    getItem: () => value,
    setItem: (_k: string, v: string) => {
      value = v
    },
    raw: () => value,
  }
}

describe('collection visits', () => {
  it('counts visits and remembers when', () => {
    const s = memoryStorage()
    recordVisit(s, 'a', 10)
    const visits = recordVisit(s, 'a', 20)
    expect(visits).toEqual({ a: { count: 2, last: 20 } })
    expect(readVisits(s)).toEqual(visits)
  })

  it('shrugs off a corrupt or hostile store', () => {
    expect(readVisits(memoryStorage('not json'))).toEqual({})
    expect(readVisits(memoryStorage('[1,2]'))).toEqual({})
    expect(
      readVisits(
        memoryStorage(
          JSON.stringify({ a: { count: 'x' }, b: { count: 1, last: 2 } }),
        ),
      ),
    ).toEqual({ b: { count: 1, last: 2 } })
    expect(VISITS_KEY).toBe('civex.collectionVisits')
  })

  it('survives storage that refuses writes', () => {
    const s = {
      getItem: () => null,
      setItem: () => {
        throw new Error('quota')
      },
    }
    expect(recordVisit(s, 'a', 1)).toEqual({ a: { count: 1, last: 1 } })
  })

  it('ranks by visits, then recency, then fills with the rest in order', () => {
    const visits = {
      a: { count: 1, last: 50 },
      b: { count: 5, last: 10 },
      c: { count: 1, last: 90 },
      gone: { count: 99, last: 99 },
    }
    expect(topCollections(visits, ['a', 'b', 'c', 'd', 'e'], 4)).toEqual([
      'b',
      'c',
      'a',
      'd',
    ])
    // a deleted collection's history is ignored
    expect(topCollections(visits, ['a'], 5)).toEqual(['a'])
  })

  it('starts from the given order when nothing has been visited', () => {
    expect(topCollections({}, ['x', 'y', 'z'], 2)).toEqual(['x', 'y'])
  })
})
