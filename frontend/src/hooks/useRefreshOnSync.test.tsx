import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeServer } from '../components/files/testSupport'
import { useRefreshOnSync } from './useRemote'

afterEach(() => vi.unstubAllGlobals())

const status = (over: Record<string, unknown> = {}) => ({
  configured: true,
  last_synced_at: '2026-10-07T10:00:00',
  last_result: {
    pulled: 0,
    pushed: 0,
    files_sent: 0,
    conflicts: 0,
    rejected: 0,
  },
  progress: null,
  pending: 0,
  ...over,
})

function setup() {
  fakeServer({ '/api/remote': status() })
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  qc.setQueryData(['remote'], status())
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  renderHook(() => useRefreshOnSync(), { wrapper })
  const refresh = vi.spyOn(qc, 'invalidateQueries')
  return { qc, refresh }
}

describe('useRefreshOnSync', () => {
  it('refreshes the page when a sync brought something in', async () => {
    const { qc, refresh } = setup()
    await act(async () => {
      qc.setQueryData(
        ['remote'],
        status({
          last_synced_at: '2026-10-07T10:01:00',
          last_result: {
            pulled: 3,
            pushed: 0,
            files_sent: 0,
            conflicts: 0,
            rejected: 0,
          },
        }),
      )
    })
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledWith())
  })

  it('leaves the page alone when a sync changed nothing', async () => {
    const { qc, refresh } = setup()
    await act(async () => {
      qc.setQueryData(
        ['remote'],
        status({ last_synced_at: '2026-10-07T10:01:00' }),
      )
    })
    expect(refresh).not.toHaveBeenCalledWith()
  })

  it('refreshes when a download of files has finished', async () => {
    const { qc, refresh } = setup()
    await act(async () => {
      qc.setQueryData(
        ['remote'],
        status({ progress: { phase: 'files', done: 1 } }),
      )
      await new Promise((r) => setTimeout(r, 20))
    })
    await act(async () => {
      qc.setQueryData(['remote'], status({ progress: null }))
    })
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledWith())
  })
})
