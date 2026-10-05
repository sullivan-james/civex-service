import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useSyncTasks } from './useSyncTasks'

const base = {
  configured: true,
  remote: 'https://a',
  project_id: 'p',
  paused: false,
  interval_seconds: 60,
  serving: false,
  pending: 0,
  open_conflicts: 0,
  files_owed: 0,
  last_synced_at: null,
  last_error: null,
  last_error_at: null,
  running: false,
}

function tasksFor(status: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(status), {
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return renderHook(() => useSyncTasks(), { wrapper })
}

afterEach(() => vi.unstubAllGlobals())

describe('useSyncTasks', () => {
  it('is quiet when all is well, or nothing is followed', async () => {
    const quiet = tasksFor(base)
    await new Promise((r) => setTimeout(r, 20))
    expect(quiet.result.current).toEqual([])
    const none = tasksFor({ ...base, configured: false })
    await new Promise((r) => setTimeout(r, 20))
    expect(none.result.current).toEqual([])
  })

  it('shows a running sync', async () => {
    const { result } = tasksFor({ ...base, running: true, pending: 2 })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0]).toMatchObject({
      title: 'Syncing…',
      spinning: true,
    })
  })

  it('says why it could not sync, and offers to try now', async () => {
    const { result } = tasksFor({ ...base, last_error: 'No route to host' })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0].tone).toBe('attention')
    expect(result.current[0].detail).toBe('No route to host')
    expect(result.current[0].actions?.map((a) => a.label)).toContain('Try now')
  })

  it('asks for a look when values were not taken as made', async () => {
    const { result } = tasksFor({ ...base, open_conflicts: 2 })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0].title).toBe('2 changes were not taken as made')
  })
})
