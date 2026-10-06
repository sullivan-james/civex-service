import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HistoryStorageCard } from './HistoryStorageCard'

const MB = 1024 * 1024
let storage: Record<string, unknown>
let reclaimed = 0

function renderCard(start: Record<string, unknown>) {
  storage = start
  reclaimed = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://x').pathname
      if (path === '/api/audit/storage/reclaim' && init?.method === 'POST') {
        reclaimed += 1
        storage = { ...storage, size_bytes: 10 * MB, free_bytes: 0 }
      }
      return new Response(JSON.stringify(storage), {
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <HistoryStorageCard />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('HistoryStorageCard', () => {
  it('offers to give unused room back, and does after asking', async () => {
    renderCard({
      whole_entries: 0,
      converting: false,
      done: null,
      total: null,
      size_bytes: 40 * MB,
      free_bytes: 30 * MB,
    })
    await userEvent.click(
      await screen.findByRole('button', { name: 'Reclaim space' }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('needs about')
    await userEvent.click(
      screen.getAllByRole('button', { name: 'Reclaim space' }).slice(-1)[0],
    )
    await waitFor(() => expect(reclaimed).toBe(1))
  })

  it('says older history is being converted, and holds the reclaim meanwhile', async () => {
    renderCard({
      whole_entries: 500,
      converting: true,
      done: 100,
      total: 600,
      size_bytes: 40 * MB,
      free_bytes: 5 * MB,
    })
    expect(await screen.findByRole('progressbar')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reclaim space' })).toBeDisabled()
  })
})
