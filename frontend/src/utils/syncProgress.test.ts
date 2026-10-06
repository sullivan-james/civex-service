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
})
