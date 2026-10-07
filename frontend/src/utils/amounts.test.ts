import { describe, expect, it } from 'vitest'
import { describeAmounts } from './amounts'

describe('describeAmounts', () => {
  it('says how many, how much, how fast and how long, like a move', () => {
    expect(
      describeAmounts({
        done: 12,
        total: 50,
        unit: 'files',
        bytesDone: 340 * 1024 * 1024,
        bytesTotal: 900 * 1024 * 1024,
        rate: 4.2 * 1024 * 1024,
        eta: 130,
      }),
    ).toBe(
      '12 of 50 files · 340 MB of 900 MB · 4.2 MB/s · about 2 minutes left',
    )
  })

  it('leaves out what is not known', () => {
    expect(describeAmounts({ done: 3, total: 12 })).toBe('3 of 12')
    expect(
      describeAmounts({ done: 3, unit: 'files', bytesDone: 2048, rate: 0 }),
    ).toBe('3 files · 2.0 KB')
  })
})
