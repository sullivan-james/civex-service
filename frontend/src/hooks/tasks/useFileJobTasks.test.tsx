import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { runFileJob } from '../fileJobs'
import { FILE_JOB_SHOW_AFTER_MS, useFileJobTasks } from './useFileJobTasks'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('file jobs in the status bar', () => {
  it('stay out of sight for the first second, so quick things do not flash', async () => {
    const { result } = renderHook(() => useFileJobTasks())
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    let done!: Promise<void>

    act(() => {
      done = runFileJob({ title: 'Preparing files…' }, () => gate)
    })
    expect(result.current).toEqual([])

    act(() => vi.advanceTimersByTime(FILE_JOB_SHOW_AFTER_MS - 100))
    expect(result.current).toEqual([])

    act(() => vi.advanceTimersByTime(100))
    expect(result.current).toHaveLength(1)
    expect(result.current[0]).toMatchObject({
      title: 'Preparing files…',
      tone: 'info',
      spinning: true,
    })

    await act(async () => {
      release()
      await done
    })
    expect(result.current).toEqual([])
  })

  it('never appear at all for a job that is over within the second', async () => {
    const { result } = renderHook(() => useFileJobTasks())

    await act(async () => {
      await runFileJob({ title: 'Quick' }, async () => undefined)
      vi.advanceTimersByTime(FILE_JOB_SHOW_AFTER_MS * 2)
    })

    expect(result.current).toEqual([])
  })

  it('show how far a move is, once it is showing', async () => {
    const { result } = renderHook(() => useFileJobTasks())
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    let done!: Promise<void>

    act(() => {
      done = runFileJob(
        { title: 'Moving 3 files to archive…' },
        async (job) => {
          job.update({
            detail: 'Waiting its turn',
            progress: { fraction: 0.5, label: '50%' },
          })
          await gate
        },
      )
    })
    act(() => vi.advanceTimersByTime(FILE_JOB_SHOW_AFTER_MS))

    expect(result.current[0]).toMatchObject({
      title: 'Moving 3 files to archive…',
      detail: 'Waiting its turn',
      progress: { fraction: 0.5, label: '50%' },
    })
    await act(async () => {
      release()
      await done
    })
  })
})
