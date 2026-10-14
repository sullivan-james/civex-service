import { describe, expect, it, vi } from 'vitest'
import type { RemoteStatus } from '../../api/remote'
import { serverFilesTasks, whyWaiting } from './useServerFilesTasks'

const status = (over: Partial<RemoteStatus> = {}): RemoteStatus =>
  ({
    configured: true,
    files_to_send: 0,
    files_waiting: null,
    files_progress: null,
    ...over,
  }) as RemoteStatus

const send = { disabled: false, onClick: vi.fn() }

describe('files and the server, as their own task', () => {
  it('is quiet when every file is on the server', () => {
    expect(serverFilesTasks(status(), send)).toEqual([])
  })

  it('offers Send now only when some can go, and says why the rest can’t', () => {
    const [task] = serverFilesTasks(
      status({
        files_to_send: 2,
        files_waiting: {
          ready: 0,
          offline: [{ volume: 'test1', files: 1, reason: 'path missing' }],
          not_here: 1,
        },
      }),
      send,
    )
    expect(task.title).toBe('2 files not on the server yet')
    expect(task.tone).toBe('attention')
    expect(task.actions?.map((a) => a.label)).toEqual(['Details'])
    expect(task.detail).toContain('on the drive “test1”, which can’t be read')
    expect(task.detail).toContain('isn’t on this computer')
  })

  it('offers Send now when files can go', () => {
    const [task] = serverFilesTasks(
      status({
        files_to_send: 3,
        files_waiting: { ready: 3, offline: [], not_here: 0 },
      }),
      send,
    )
    expect(task.actions?.map((a) => a.label)).toContain('Send now')
    expect(task.detail).toBe('3 files will go up in the background.')
  })

  it('shows files going up as a bar of their own', () => {
    const [task] = serverFilesTasks(
      status({
        files_to_send: 5,
        files_progress: {
          phase: 'sending',
          done: 2,
          total: 5,
          kind: null,
          bytes_done: 1024,
          rate: 0,
        },
      }),
      send,
    )
    expect(task.id).toBe('server-files')
    expect(task.progress?.fraction).toBeCloseTo(0.4)
  })

  it('words one file and several', () => {
    expect(whyWaiting({ ready: 1, offline: [], not_here: 2 })).toBe(
      '1 file will go up in the background. 2 files aren’t on this computer, and the server hasn’t got them either: a computer that has them must send them.',
    )
  })
})
