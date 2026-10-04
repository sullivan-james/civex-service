import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { TaskStatusBar } from './TaskStatusBar'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const progress = (over = {}) => ({
  files_total: 40,
  files_done: 14,
  files_skipped: 0,
  files_failed: 0,
  bytes_total: 4000,
  bytes_done: 1400,
  current: null,
  current_bytes: 0,
  current_total: 0,
  rate_bytes_per_second: 2048,
  eta_seconds: 90,
  message: '',
  ...over,
})

const transfer = (over = {}) => ({
  id: 't1',
  kind: 'drain',
  status: 'running',
  spec: {
    kind: 'drain',
    targets: ['b'],
    sources: ['a'],
    collection_ids: [],
    include_shared: false,
    verify: 'copy',
    freeze_sources: true,
  },
  plan: null,
  progress: progress(),
  failures: [],
  failures_total: 0,
  pause_reason: null,
  auto_resume: false,
  error: null,
  control: null,
  frozen: {},
  live: true,
  created_at: '2026-10-04T10:00:00Z',
  started_at: null,
  finished_at: null,
  updated_at: null,
  ...over,
})

let transfers: ReturnType<typeof transfer>[]
let calls: { method: string; path: string }[]

beforeEach(() => {
  calls = []
  transfers = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      calls.push({ method: init?.method ?? 'GET', path: url.pathname })
      if (url.pathname === '/api/store/transfers') return json(transfers)
      if (url.pathname === '/api/automation')
        return json({ paused: false, pending: 0, running: 0, cancelled: 0 })
      return json(transfer({ control: 'pause' }))
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TaskStatusBar />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the status bar, for file moves', () => {
  it('renders nothing when no move is in progress', async () => {
    transfers = [transfer({ status: 'completed', live: false })]
    const { container } = renderIt()
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))
    await new Promise((r) => setTimeout(r, 20))
    expect(container).toBeEmptyDOMElement()
  })

  it('shows a running move live: share, files, speed, time left', async () => {
    transfers = [transfer()]
    renderIt()
    expect(await screen.findByText('Emptying a')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute(
      'aria-valuenow',
      '35',
    )
    expect(screen.getByText(/14 of 40 files/)).toBeInTheDocument()
    expect(screen.getByText(/2\.0 KB\/s/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Details' })).toHaveAttribute(
      'href',
      '/settings/storage?tab=tasks',
    )
  })

  it('pauses the running move from anywhere', async () => {
    transfers = [transfer()]
    renderIt()
    await userEvent.click(await screen.findByRole('button', { name: 'Pause' }))
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.path.endsWith('/t1/pause')),
      ).toBe(true),
    )
  })

  it('counts the moves waiting behind the running one', async () => {
    transfers = [
      transfer(),
      transfer({ id: 't2', status: 'queued', live: false }),
      transfer({ id: 't3', status: 'queued', live: false }),
    ]
    renderIt()
    expect(await screen.findByText('2 more waiting')).toBeInTheDocument()
  })

  it('says so when a move is waiting for a drive, and that it carries on', async () => {
    transfers = [
      transfer({
        status: 'paused',
        auto_resume: true,
        live: false,
        pause_reason: "Volume 'b' isn't responding.",
      }),
    ]
    renderIt()
    expect(await screen.findByText(/Emptying a is waiting/)).toBeInTheDocument()
    expect(screen.getByText(/carries on by itself/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull()
  })

  it('says how many moves are waiting when none has started yet', async () => {
    transfers = [transfer({ status: 'queued', live: false })]
    renderIt()
    expect(
      await screen.findByText(/1 move waiting to start/),
    ).toBeInTheDocument()
  })
})
