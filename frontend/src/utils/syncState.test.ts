import { describe, it, expect } from 'vitest'
import type { RemoteStatus } from '../api/remote'
import { ago, syncButtonState } from './syncState'

const NOW = Date.parse('2026-10-05T12:00:00Z')
const base: RemoteStatus = {
  configured: true,
  remote: 'https://a',
  project_id: 'p',
  paused: false,
  interval_seconds: 60,
  download_files: 'all',
  files_to_fetch: 0,
  serving: false,
  pending: 0,
  open_conflicts: 0,
  last_synced_at: '2026-10-05T11:57:00Z',
  last_error: null,
  last_error_at: null,
  running: false,
  last_result: null,
  progress: null,
  connecting: false,
  connect_error: null,
}

describe('syncButtonState', () => {
  it('says synced, and when, when there is nothing to send', () => {
    const s = syncButtonState(base, false, NOW)
    expect(s).toMatchObject({ label: 'Synced 3 min ago', tone: 'ok' })
  })
  it('says how many changes are waiting', () => {
    expect(syncButtonState({ ...base, pending: 26 }, false, NOW)).toMatchObject(
      { label: 'Sync · 26 to send', tone: 'needed' },
    )
  })
  it('says it failed', () => {
    expect(
      syncButtonState({ ...base, last_error: 'No route' }, false, NOW).tone,
    ).toBe('error')
  })
  it('is busy while running or starting', () => {
    expect(syncButtonState({ ...base, running: true }, false, NOW).tone).toBe(
      'busy',
    )
    expect(syncButtonState(base, true, NOW).label).toBe('Syncing…')
  })
  it('asks for a review when there are conflicts', () => {
    expect(
      syncButtonState({ ...base, open_conflicts: 2 }, false, NOW).label,
    ).toBe('Sync · 2 to review')
  })
  it('has a plain label before the first sync', () => {
    expect(
      syncButtonState({ ...base, last_synced_at: null }, false, NOW).label,
    ).toBe('Sync')
  })
})

describe('ago', () => {
  it('reads naturally', () => {
    expect(ago('2026-10-05T11:59:50Z', NOW)).toBe('just now')
    expect(ago('2026-10-05T09:00:00Z', NOW)).toBe('3 h ago')
    expect(ago(null, NOW)).toBe('never')
  })
})
