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

  it('counts only what this computer can send', () => {
    const [task] = serverFilesTasks(
      status({
        files_to_send: 1,
        files_waiting: {
          ready: 0,
          offline: [{ volume: 'test1', files: 1, reason: 'path missing' }],
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
  })

  it('offers Send now when files can go', () => {
    const [task] = serverFilesTasks(
      status({
        files_to_send: 3,
        files_waiting: { ready: 3, offline: [] },
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
      }),
    ).toBe(
      '2 files will go up in the background. 1 file is on the drive “a”, which can’t be read; it goes once it is plugged in.',
    )
  })
})

describe('a blank copy only downloads', () => {
  it('says files the server lacks are the other device’s, never ours to send', () => {
    const tasks = serverFilesTasks(
      status({ files_arriving: 2, files_missing: 1 }),
      send,
    )
    expect(tasks.map((t) => t.title)).toEqual([
      '2 files aren’t on the server yet',
      '1 file missing',
    ])
    expect(tasks[0].detail).toBe(
      'The device that added them hasn’t uploaded them.',
    )
    const said = JSON.stringify(tasks)
    expect(said).not.toMatch(/nothing here can send|Ignore|Send now/)
  })

  it('holds the counts back until the copy is done', () => {
    const tasks = serverFilesTasks(
      status({
        files_arriving: 2,
        files_missing: 1,
        progress: { phase: 'copying', done: 5, total: 100, kind: 'record' },
      }),
      send,
    )
    expect(tasks).toEqual([])
  })

  it('offers to download every file once, with how many', () => {
    const keepAll = { disabled: false, onClick: vi.fn(), bytes: 2_000_000_000 }
    const [offer] = serverFilesTasks(
      status({
        download_files: 'opened',
        files_not_here: 3854,
        serving: false,
      }),
      send,
      keepAll,
    )
    expect(offer.actions?.[0].label).toMatch(
      /^Download all files \(3,854 files, [\d.]+ GB\)$/,
    )
    offer.actions?.[0].onClick?.()
    expect(keepAll.onClick).toHaveBeenCalled()
    expect(
      serverFilesTasks(
        status({ download_files: 'all', files_not_here: 3854 }),
        send,
        keepAll,
      ),
    ).toEqual([])
  })
})
