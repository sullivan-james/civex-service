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

  it('counts history in changes, and has no bar when the total is unknown', () => {
    const text = describeSyncProgress({
      phase: 'history',
      done: 400,
      total: null,
      kind: null,
    })
    expect(text.title).toBe('Fetching earlier history')
    expect(text.detail).toBe('changes · 400')
    expect(text.fraction).toBeNull()
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
})
