import { describe, it, expect } from 'vitest'
import {
  markReviewed,
  positionOf,
  readSession,
  reviewedField,
  rememberReviewedField,
  startSession,
} from './triage'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial }
  return {
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => {
      data[k] = v
    },
  }
}

describe('triage session', () => {
  it('freezes the list and reads it back', () => {
    const s = memoryStorage()
    const session = startSession(s, 'Missing table', ['a', 'b', 'c'])
    expect(readSession(s, session.id)).toEqual(session)
  })

  it('has no session without a token, or for a stale or corrupt one', () => {
    const s = memoryStorage({ 'civex.triage.bad': 'nope' })
    expect(readSession(s, null)).toBeNull()
    expect(readSession(s, 'gone')).toBeNull()
    expect(readSession(s, 'bad')).toBeNull()
  })

  it('counts a record reviewed once however often it is marked', () => {
    const s = memoryStorage()
    const session = startSession(s, 'x', ['a', 'b'])
    markReviewed(s, session, 'a')
    const again = markReviewed(s, readSession(s, session.id)!, 'a')
    expect(again.reviewed).toEqual(['a'])
    expect(readSession(s, session.id)!.reviewed).toEqual(['a'])
  })

  it('locates a record, and hides the bar for one outside the list', () => {
    const session = startSession(memoryStorage(), 'x', ['a', 'b', 'c'])
    expect(positionOf(session, 'a')).toEqual({
      index: 1,
      total: 3,
      previousId: null,
      nextId: 'b',
    })
    expect(positionOf(session, 'c')?.nextId).toBeNull()
    expect(positionOf(session, 'zzz')).toBeNull()
  })
})

describe('reviewed field', () => {
  const fields = [
    { name: 'note', type: 'string' },
    { name: 'checked', type: 'boolean' },
    { name: 'reviewed', type: 'boolean' },
  ]

  it('prefers a field named reviewed, then any boolean', () => {
    expect(reviewedField(memoryStorage(), 'sel', fields)).toBe('reviewed')
    expect(reviewedField(memoryStorage(), 'sel', [fields[0], fields[1]])).toBe(
      'checked',
    )
  })

  it('honours a remembered choice while it still exists', () => {
    const s = memoryStorage()
    rememberReviewedField(s, 'sel', 'checked')
    expect(reviewedField(s, 'sel', fields)).toBe('checked')
    expect(reviewedField(s, 'sel', [fields[2]])).toBe('reviewed')
  })

  it('is null when the schema has no boolean field', () => {
    expect(reviewedField(memoryStorage(), 'sel', [fields[0]])).toBeNull()
  })
})
