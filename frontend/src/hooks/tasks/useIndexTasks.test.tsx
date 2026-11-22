import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { FieldIndexReport } from '../../api/indexes'
import { useIndexTasks } from './useIndexTasks'

const idle: FieldIndexReport = {
  fields: [],
  stale: [],
  in_step: true,
  building: false,
  progress: null,
  elsewhere: false,
  error: null,
}

function tasksFor(report: FieldIndexReport, features?: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      const body = url.pathname.endsWith('/status/features')
        ? features
          ? { features }
          : {}
        : report
      return new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return renderHook(() => useIndexTasks(), { wrapper })
}

afterEach(() => vi.unstubAllGlobals())

describe('useIndexTasks', () => {
  it('is quiet when nothing is being built', async () => {
    const { result } = tasksFor(idle)
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current).toEqual([])
  })

  it('shows the build with which one of how many', async () => {
    const { result } = tasksFor({
      ...idle,
      in_step: false,
      building: true,
      progress: {
        done: 1,
        total: 4,
        schema_label: 'Sample',
        field_label: 'Depth',
        waiting: false,
        yielded: 0,
      },
    })
    await waitFor(() => expect(result.current).toHaveLength(1))
    const task = result.current[0]
    expect(task.title).toBe('Speeding up sorting on Sample')
    expect(task.progress?.count).toBe('2 of 4')
    expect(task.progress?.fraction).toBe(0.25)
    expect(task.detail).toBe('Indexing Depth')
  })

  it('says when it is waiting for saving to pause', async () => {
    const { result } = tasksFor({
      ...idle,
      in_step: false,
      building: true,
      progress: {
        done: 0,
        total: 1,
        schema_label: 'Sample',
        field_label: 'Depth',
        waiting: true,
        yielded: 2,
      },
    })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0].detail).toBe(
      'Waiting for a moment when nobody is saving',
    )
    expect(result.current[0].spinning).toBe(false)
  })

  it('asks nothing of a host without database administration', async () => {
    const { result } = tasksFor({ ...idle, building: true, elsewhere: true }, [
      'volumes',
    ])
    await new Promise((r) => setTimeout(r, 30))
    expect(result.current).toEqual([])
  })
})
