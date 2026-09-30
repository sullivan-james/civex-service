import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import {
  recordCollectionVisit,
  useFrequentCollections,
} from './useFrequentCollections'

const COLLECTIONS = ['alpha', 'beta', 'gamma', 'delta'].map((name) => ({
  id: `id-${name}`,
  name,
  description: null,
  record_count: 0,
}))

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () => new Response(JSON.stringify(COLLECTIONS), { status: 200 }),
    ),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('useFrequentCollections', () => {
  it('starts from the collection list, then follows what gets opened', async () => {
    const { result } = renderHook(() => useFrequentCollections(2), { wrapper })
    await waitFor(() =>
      expect(result.current.map((c) => c.name)).toEqual(['alpha', 'beta']),
    )

    act(() => {
      recordCollectionVisit('gamma')
      recordCollectionVisit('gamma')
      recordCollectionVisit('delta')
    })
    expect(result.current.map((c) => c.name)).toEqual(['gamma', 'delta'])
  })

  it('forgets collections that no longer exist', async () => {
    localStorage.setItem(
      'civex.collectionVisits',
      JSON.stringify({ deleted: { count: 50, last: 1 } }),
    )
    const { result } = renderHook(() => useFrequentCollections(5), { wrapper })
    await waitFor(() => expect(result.current).toHaveLength(4))
    expect(result.current.map((c) => c.name)).not.toContain('deleted')
  })
})
