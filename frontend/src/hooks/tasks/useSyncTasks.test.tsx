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
  download_files: 'all',
  files_to_fetch: 0,
  files_to_send: 0,
  serving: false,
  pending: 0,
  open_conflicts: 0,
  last_synced_at: null,
  last_error: null,
  last_error_at: null,
  running: false,
  last_result: null,
  progress: null,
  connecting: false,
  connect_error: null,
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
    expect(result.current[0].actions).toEqual([
      { label: 'Review', to: '/sync/review' },
    ])
  })

  it('shows a copy from the server with a bar and what it is on', async () => {
    const { result } = tasksFor({
      ...base,
      configured: false,
      connecting: true,
      progress: { phase: 'copying', done: 50, total: 200, kind: 'record' },
    })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0]).toMatchObject({
      title: 'Copying the project from the server',
      // The numbers beside the bar, not repeated as a detail.
      progress: { fraction: 0.25, count: '50 of 200 records' },
      tone: 'info',
    })
    expect(result.current[0].detail).toBeUndefined()
  })

  it('says when connecting stopped', async () => {
    const { result } = tasksFor({ ...base, connect_error: 'Server went away' })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0]).toMatchObject({
      title: 'Could not connect',
      tone: 'attention',
      detail: 'Server went away',
    })
  })

  it('says when files here are not on the server yet', async () => {
    const { result } = tasksFor({ ...base, files_to_send: 3 })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0]).toMatchObject({
      title: '3 files not on the server yet',
      tone: 'info',
    })
    expect(result.current[0].actions?.map((a) => a.label)).toContain('Send now')
  })

  it('counts files with changes while a sync runs or has failed', async () => {
    const running = tasksFor({
      ...base,
      running: true,
      pending: 1,
      files_to_send: 2,
    })
    await waitFor(() => expect(running.result.current).toHaveLength(1))
    expect(running.result.current[0].detail).toBe(
      '1 change and 2 files to send',
    )
    const failed = tasksFor({ ...base, last_error: 'gone', files_to_send: 1 })
    await waitFor(() => expect(failed.result.current).toHaveLength(1))
    expect(failed.result.current[0].note).toBe(
      '1 file saved here, not yet sent',
    )
  })
})
