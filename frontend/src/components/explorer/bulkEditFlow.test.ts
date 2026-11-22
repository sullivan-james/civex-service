import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient } from '@tanstack/react-query'
import { useFileJobs } from '../../hooks/fileJobs'
import { fakeServer, json } from '../files/testSupport'
import type { FlowContext } from '../files/fileFlows'
import { editRecords } from './bulkEditFlow'

afterEach(() => vi.unstubAllGlobals())

const BODY = { ids: ['a', 'b'], changes: { status: 'checked' } }

function context() {
  const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn() }
  const ctx: FlowContext = {
    toast,
    problem: vi.fn(),
    qc: new QueryClient(),
    progressMs: 5,
  }
  return { ctx, toast }
}

function gate() {
  let open!: () => void
  const wait = new Promise<void>((r) => (open = r))
  return { wait, open }
}

const result = (over = {}) => ({
  changed: 1200,
  unchanged: 3,
  skipped: 2,
  skipped_records: [],
  runs: 0,
  stopped: false,
  ...over,
})

describe('editing many records', () => {
  it('runs as a job that shows how far it has got, and can be stopped', async () => {
    const g = gate()
    const calls = fakeServer({
      '/api/records/bulk-edit': async () => {
        await g.wait
        return json(result({ changed: 500, stopped: true }))
      },
      '/api/file-access/progress': () =>
        json({ phase: 'Changing records', done: 500, total: 1205 }),
    })
    const { ctx, toast } = context()
    const jobs = renderHook(() => useFileJobs())

    const running = editRecords(ctx, BODY)
    await vi.waitFor(() =>
      expect(jobs.result.current[0]?.progress?.count).toBe('500 of 1,205'),
    )
    expect(jobs.result.current[0].title).toBe('Changing records…')

    jobs.result.current[0].stop?.()
    await vi.waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && /\/progress\/.+\/cancel$/.test(c.path),
        ),
      ).toBe(true),
    )
    g.open()
    await running

    expect(toast.success).toHaveBeenCalledWith('Stopped: 500 records changed')
    expect(jobs.result.current).toEqual([])
  })

  it('says what changed and what was left when it is done', async () => {
    fakeServer({
      '/api/records/bulk-edit': result(),
      '/api/file-access/progress': () => json({}, 404),
    })
    const { ctx, toast } = context()

    await editRecords(ctx, BODY)

    expect(toast.success).toHaveBeenCalledWith(
      '1,200 records changed, 2 left as they were',
    )
  })

  it('says so when the server refuses it', async () => {
    fakeServer({
      '/api/records/bulk-edit': () =>
        json({ detail: 'Choose a field to set or clear' }, 422),
      '/api/file-access/progress': () => json({}, 404),
    })
    const { ctx, toast } = context()

    await editRecords(ctx, BODY)

    expect(toast.error).toHaveBeenCalledWith('Choose a field to set or clear')
  })
})
