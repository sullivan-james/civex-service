import { describe, it, expect } from 'vitest'
import type { RemoteStatus } from '../api/remote'
import { syncNotice } from './syncToast'

const status = (over: Partial<RemoteStatus> = {}): RemoteStatus => ({
  configured: true,
  remote: 'https://a',
  project_id: 'p',
  paused: false,
  interval_seconds: 60,
  serving: false,
  pending: 0,
  open_conflicts: 0,
  last_synced_at: 'T1',
  last_error: null,
  last_error_at: null,
  running: false,
  last_result: null,
  ...over,
})
const before = { last_synced_at: 'T1', last_error: null, last_error_at: null }
const result = (over = {}) => ({
  pulled: 0,
  pushed: 0,
  files_sent: 0,
  conflicts: 0,
  rejected: 0,
  ...over,
})

describe('syncNotice', () => {
  it('says nothing on the first look or when nothing finished', () => {
    expect(syncNotice(null, status(), true)).toBeNull()
    expect(syncNotice(before, status(), true)).toBeNull()
  })
  it('reports what a finished sync did', () => {
    const n = syncNotice(
      before,
      status({
        last_synced_at: 'T2',
        last_result: result({ pulled: 3, pushed: 1 }),
      }),
      false,
    )
    expect(n).toEqual({
      variant: 'success',
      message: 'Synced: received 3 changes, sent 1 change',
    })
  })
  it('stays quiet about an automatic sync that did nothing, but answers a request', () => {
    const after = status({ last_synced_at: 'T2', last_result: result() })
    expect(syncNotice(before, after, false)).toBeNull()
    expect(syncNotice(before, after, true)?.message).toBe('Already up to date')
  })
  it('flags conflicts', () => {
    const n = syncNotice(
      before,
      status({ last_synced_at: 'T2', last_result: result({ conflicts: 2 }) }),
      false,
    )
    expect(n?.variant).toBe('error')
    expect(n?.message).toContain('2 values to review')
  })
  it('tells a new failure once, not at every retry', () => {
    const failed = status({ last_error: 'down', last_error_at: 'E1' })
    expect(syncNotice(before, failed, false)?.variant).toBe('error')
    const again = status({ last_error: 'down', last_error_at: 'E2' })
    expect(
      syncNotice(
        { ...before, last_error: 'down', last_error_at: 'E1' },
        again,
        false,
      ),
    ).toBeNull()
    expect(
      syncNotice(
        { ...before, last_error: 'down', last_error_at: 'E1' },
        again,
        true,
      )?.variant,
    ).toBe('error')
  })
})
