import { describe, it, expect } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { runFileJob, useFileJobs } from './fileJobs'

describe('file jobs', () => {
  it('are listed while they run, and gone when they finish', async () => {
    const { result } = renderHook(() => useFileJobs())
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))

    let done!: Promise<string>
    act(() => {
      done = runFileJob({ title: 'Preparing files…' }, async () => {
        await gate
        return 'ok'
      })
    })

    expect(result.current.map((j) => j.title)).toEqual(['Preparing files…'])
    await act(async () => {
      release()
      await done
    })
    expect(await done).toBe('ok')
    expect(result.current).toEqual([])
  })

  it('can say how far along they are as they go', async () => {
    const { result } = renderHook(() => useFileJobs())
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    let done!: Promise<void>

    act(() => {
      done = runFileJob({ title: 'Moving 3 files…' }, async (job) => {
        job.update({
          detail: 'Waiting its turn',
          progress: { fraction: 0.4, label: '40%' },
        })
        await gate
      })
    })

    expect(result.current[0]).toMatchObject({
      title: 'Moving 3 files…',
      detail: 'Waiting its turn',
      progress: { fraction: 0.4, label: '40%' },
    })
    await act(async () => {
      release()
      await done
    })
  })

  it('are removed, and the error handed back, when the work fails', async () => {
    const { result } = renderHook(() => useFileJobs())

    await act(async () => {
      await expect(
        runFileJob({ title: 'x' }, async () => {
          throw new Error('the drive went')
        }),
      ).rejects.toThrow('the drive went')
    })

    expect(result.current).toEqual([])
  })

  it('can run side by side, each with its own row', async () => {
    const { result } = renderHook(() => useFileJobs())
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    let a!: Promise<void>
    let b!: Promise<void>

    act(() => {
      a = runFileJob({ title: 'one' }, () => gate)
      b = runFileJob({ title: 'two' }, () => gate)
    })

    expect(result.current.map((j) => j.title)).toEqual(['one', 'two'])
    expect(new Set(result.current.map((j) => j.id)).size).toBe(2)
    await act(async () => {
      release()
      await Promise.all([a, b])
    })
  })
})
