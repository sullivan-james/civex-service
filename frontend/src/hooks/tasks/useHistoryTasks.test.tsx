import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useHistoryTasks } from './useHistoryTasks'

function tasksFor(storage: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(storage), {
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return renderHook(() => useHistoryTasks(), { wrapper })
}

afterEach(() => vi.unstubAllGlobals())

const idle = {
  whole_entries: 0,
  converting: false,
  done: null,
  total: null,
  size_bytes: 1000,
  free_bytes: 0,
}

describe('useHistoryTasks', () => {
  it('is quiet when nothing is being converted', async () => {
    const { result } = tasksFor(idle)
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current).toEqual([])
  })

  it('shows the conversion with how far it has got', async () => {
    const { result } = tasksFor({
      ...idle,
      whole_entries: 750,
      converting: true,
      done: 250,
      total: 1000,
    })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0]).toMatchObject({
      title: 'Tidying history',
      progress: { fraction: 0.25 },
      tone: 'info',
    })
  })
})
