import { describe, expect, it } from 'vitest'
import { describeSyncProgress } from './syncProgress'

describe('describeSyncProgress', () => {
  it('says what is being copied and how far along it is', () => {
    expect(
      describeSyncProgress({
        phase: 'copying',
        done: 12000,
        total: 48000,
        kind: 'record',
      }),
    ).toEqual({
      title: 'Copying the project from the server',
      detail: `records · ${(12000).toLocaleString()} of ${(48000).toLocaleString()}`,
      count: `${(12000).toLocaleString()} of ${(48000).toLocaleString()} records`,
      fraction: 0.25,
    })
  })

  it('counts files while downloading them', () => {
    const text = describeSyncProgress({
      phase: 'files',
      done: 3,
      total: 12,
      kind: null,
    })
    expect(text.title).toBe('Downloading files from the server')
    expect(text.detail).toBe('files · 3 of 12')
  })

  it('never goes past the end', () => {
    expect(
      describeSyncProgress({
        phase: 'filling',
        done: 12,
        total: 10,
        kind: 'view',
      }).fraction,
    ).toBe(1)
  })

  it('describes sending files to the server', () => {
    const text = describeSyncProgress({
      phase: 'sending',
      done: 1,
      total: 4,
      kind: null,
    })
    expect(text.title).toBe('Sending files to the server')
    expect(text.detail).toBe('files · 1 of 4')
  })

  it('says how much is being sent in all, and goes by bytes', () => {
    const text = describeSyncProgress({
      phase: 'sending',
      done: 1,
      total: 4,
      kind: null,
      bytes_done: 250 * 1024 * 1024,
      bytes_total: 1024 * 1024 * 1024,
      rate: 10 * 1024 * 1024,
    })
    expect(text.count).toBe(
      '1 of 4 files · 250 MB of 1.0 GB · 10.0 MB/s · about 77 seconds left',
    )
    expect(text.fraction).toBeCloseTo(250 / 1024)
  })

  it('shows the size from the start, before anything has gone', () => {
    const text = describeSyncProgress({
      phase: 'sending',
      done: 0,
      total: 2,
      kind: null,
      bytes_done: 0,
      bytes_total: 2048,
    })
    expect(text.count).toContain('of 2.0 KB')
    expect(text.fraction).toBe(0)
  })

  it('says how many files could not be read here, apart from those sent', () => {
    const text = describeSyncProgress({
      phase: 'sending',
      done: 8,
      total: 10,
      kind: null,
      owed: 2,
      bytes_done: 800,
      bytes_total: 1000,
    })
    expect(text.count).toContain('2 not readable here')
    expect(text.count).toContain('8 of 10 files')
  })

  it('says how many changes are being prepared, and counts those pulled', () => {
    const prep = describeSyncProgress({
      phase: 'preparing',
      done: 0,
      total: 168084,
      kind: null,
    })
    expect(prep.title).toBe('Preparing 168,084 changes to send')
    expect(prep.fraction).toBeNull()
    const pull = describeSyncProgress({
      phase: 'pulling',
      done: 400,
      total: 1000,
      kind: null,
    })
    expect(pull.title).toBe('Getting changes from the server')
    expect(pull.detail).toBe('changes · 400 of 1,000')
  })
})
