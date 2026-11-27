import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useFileJobs } from '../../hooks/fileJobs'
import { recordsApi } from '../../api/records'
import { fakeServer, json } from './testSupport'
import { withProgress } from './fileFlows'

afterEach(() => vi.unstubAllGlobals())

describe('a long delete, restore or move', () => {
  it('shows records of records in the status bar and can be stopped', async () => {
    let open!: () => void
    const wait = new Promise<void>((r) => (open = r))
    const calls = fakeServer({
      '/api/records/bulk-delete': async () => {
        await wait
        return json({ deleted: 12400, records: 12400, stopped: true })
      },
      '/api/file-access/progress': () =>
        json({ phase: 'Deleting records', done: 12400, total: 50000 }),
    })
    const jobs = renderHook(() => useFileJobs())

    const running = withProgress(
      'Deleting records…',
      (pid) => recordsApi.deleteMany(['a'], pid),
      true,
      { progressMs: 5 },
    )
    await vi.waitFor(() =>
      expect(jobs.result.current[0]?.progress?.count).toBe('12,400 of 50,000'),
    )
    expect(jobs.result.current[0].title).toBe('Deleting records…')

    jobs.result.current[0].stop?.()
    await vi.waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && /\/progress\/.+\/cancel$/.test(c.path),
        ),
      ).toBe(true),
    )
    open()
    expect(await running).toEqual({
      deleted: 12400,
      records: 12400,
      stopped: true,
    })
    expect(jobs.result.current).toEqual([])
  })

  it('tags the request so the server can report on it', async () => {
    const calls = fakeServer({
      '/api/records/move': json({ roots: 1, records: 1, collection: 'x' }),
      '/api/file-access/progress': () => json({}, 404),
    })
    await withProgress('Moving records…', (pid) =>
      recordsApi.move({ ids: ['a'], to: 'x' }, pid),
    )
    const move = calls.find((c) => c.path.endsWith('/records/move'))
    expect(move).toBeDefined()
  })
})
