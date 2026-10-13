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

  it('counts only what this computer can send, and says missing files apart', () => {
    const [task, missing] = serverFilesTasks(
      status({
        files_to_send: 1,
        files_waiting: {
          ready: 0,
          offline: [{ volume: 'test1', files: 1, reason: 'path missing' }],
          missing: 1,
        },
      }),
      send,
    )
    expect(task.title).toBe('1 file to send to the server')
    expect(task.tone).toBe('attention')
    expect(task.actions?.map((a) => a.label)).toEqual(['See files'])
    expect(task.detail).toBe(
      '1 file is on the drive “test1”, which can’t be read (path missing); it goes once it is plugged in.',
    )
    expect(missing.title).toBe('1 file missing')
    expect(missing.tone).toBe('attention')
    expect(missing.detail).toBe(
      'It isn’t on this computer, and the server hasn’t got it, so nothing here can send it.',
    )
    expect(missing.actions?.[0]).toMatchObject({
      label: 'See which',
      to: '/collections?tab=records&show=files&files.place=missing',
    })
  })

  it('says missing files even when nothing is left to send', () => {
    const tasks = serverFilesTasks(
      status({
        files_to_send: 0,
        files_waiting: { ready: 0, offline: [], missing: 2 },
      }),
      send,
    )
    expect(tasks.map((t) => t.title)).toEqual(['2 files missing'])
  })

  it('offers Send now when files can go', () => {
    const [task] = serverFilesTasks(
      status({
        files_to_send: 3,
        files_waiting: { ready: 3, offline: [], missing: 0 },
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
    expect(
      whyWaiting({
        ready: 2,
        offline: [{ volume: 'a', files: 1, reason: '' }],
        missing: 0,
      }),
    ).toBe(
      '2 files will go up in the background. 1 file is on the drive “a”, which can’t be read; it goes once it is plugged in.',
    )
  })
})
