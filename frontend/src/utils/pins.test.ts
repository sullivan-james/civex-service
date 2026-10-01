import { describe, it, expect } from 'vitest'
import {
  MAX_RECENTS,
  PINS_KEY,
  RECENTS_KEY,
  parseTargets,
  pushRecent,
  readPins,
  readRecents,
  targetKeys,
  togglePin,
  type NavTarget,
} from './pins'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial }
  return {
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => {
      data[k] = v
    },
  }
}

const collection = (id: string): NavTarget => ({
  key: targetKeys.collection(id),
  kind: 'collection',
  label: id,
  to: `/collections/${id}`,
})

describe('pins', () => {
  it('pins in the order added and unpins on a second toggle', () => {
    const s = memoryStorage()
    togglePin(s, collection('a'))
    togglePin(s, collection('b'))
    expect(readPins(s).map((p) => p.label)).toEqual(['a', 'b'])
    togglePin(s, collection('a'))
    expect(readPins(s).map((p) => p.label)).toEqual(['b'])
  })

  it('shrugs off a corrupt or hostile store', () => {
    expect(parseTargets('not json')).toEqual([])
    expect(parseTargets('{"a":1}')).toEqual([])
    expect(
      parseTargets(JSON.stringify([{ key: 1 }, collection('ok')])),
    ).toEqual([collection('ok')])
    expect(readPins(memoryStorage({ [PINS_KEY]: 'nope' }))).toEqual([])
  })

  it('survives storage that throws', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    }
    expect(readPins(broken)).toEqual([])
    expect(() => togglePin(broken, collection('a'))).not.toThrow()
    expect(() => pushRecent(broken, collection('a'))).not.toThrow()
  })
})

describe('recents', () => {
  it('moves a reopened item to the front without duplicating it', () => {
    const s = memoryStorage()
    pushRecent(s, collection('a'))
    pushRecent(s, collection('b'))
    pushRecent(s, collection('a'))
    expect(readRecents(s).map((r) => r.label)).toEqual(['a', 'b'])
  })

  it('keeps only the most recent few', () => {
    const s = memoryStorage()
    for (let i = 0; i < MAX_RECENTS + 5; i++) pushRecent(s, collection(`c${i}`))
    const recents = readRecents(s)
    expect(recents).toHaveLength(MAX_RECENTS)
    expect(recents[0].label).toBe(`c${MAX_RECENTS + 4}`)
    expect(s.getItem(RECENTS_KEY)).not.toBeNull()
  })
})
