import { describe, it, expect, vi } from 'vitest'
import { createBatcher } from './batcher'

const found = (keys: string[], skip: string[] = []) =>
  new Map(
    keys.filter((k) => !skip.includes(k)).map((k) => [k, k.toUpperCase()]),
  )

describe('createBatcher', () => {
  it('turns many asks made together into one fetch', async () => {
    const fetchBatch = vi.fn(async (keys: string[]) => found(keys))
    const { load } = createBatcher(fetchBatch, { wait: 5 })

    const got = await Promise.all(['a', 'b', 'c', 'd'].map((k) => load(k)))

    expect(got).toEqual(['A', 'B', 'C', 'D'])
    expect(fetchBatch).toHaveBeenCalledTimes(1)
    expect(fetchBatch).toHaveBeenCalledWith(['a', 'b', 'c', 'd'])
  })

  it('fetches a key asked for twice in a window once, and answers both', async () => {
    const fetchBatch = vi.fn(async (keys: string[]) => found(keys))
    const { load } = createBatcher(fetchBatch, { wait: 5 })

    const [first, second] = await Promise.all([load('a'), load('a')])

    expect(first).toBe('A')
    expect(second).toBe('A')
    expect(fetchBatch).toHaveBeenCalledWith(['a'])
  })

  it('answers undefined for a key the fetch did not find, without failing the rest', async () => {
    const { load } = createBatcher(async (keys) => found(keys, ['gone']), {
      wait: 5,
    })

    const [here, gone] = await Promise.all([load('here'), load('gone')])

    expect(here).toBe('HERE')
    expect(gone).toBeUndefined()
  })

  it('splits a large batch, so no request is oversized', async () => {
    const fetchBatch = vi.fn(async (keys: string[]) => found(keys))
    const { load } = createBatcher(fetchBatch, { wait: 5, max: 3 })

    const keys = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    const got = await Promise.all(keys.map((k) => load(k)))

    expect(got).toEqual(keys.map((k) => k.toUpperCase()))
    expect(fetchBatch.mock.calls.map((c) => c[0].length)).toEqual([3, 3, 1])
  })

  it('starts a new batch for asks made after the window', async () => {
    const fetchBatch = vi.fn(async (keys: string[]) => found(keys))
    const { load } = createBatcher(fetchBatch, { wait: 5 })

    await load('a')
    await load('b')

    expect(fetchBatch).toHaveBeenCalledTimes(2)
  })

  it('rejects every waiting ask when the fetch fails', async () => {
    const { load } = createBatcher(
      async () => {
        throw new Error('server down')
      },
      { wait: 5 },
    )

    const results = await Promise.allSettled([load('a'), load('b')])

    expect(results.map((r) => r.status)).toEqual(['rejected', 'rejected'])
  })
})
