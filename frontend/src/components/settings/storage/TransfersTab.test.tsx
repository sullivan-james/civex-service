import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '../../ui/ToastProvider'
import { MemoryRouter } from 'react-router'
import { TasksTab } from './TasksTab'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const GB = 1024 ** 3
const volume = (name: string) => ({
  name,
  path: `/media/${name}`,
  allocated_gb: null,
  civex_used_bytes: 0,
  disk_free_bytes: 500 * GB,
  disk_total_bytes: 1000 * GB,
  available: true,
  state: 'online',
  reason: '',
  fix: '',
  warning: false,
  in_queue: false,
  network: false,
})

const progress = (over = {}) => ({
  files_total: 10,
  files_done: 4,
  files_skipped: 0,
  files_failed: 0,
  bytes_total: 1000,
  bytes_done: 400,
  current: null,
  current_bytes: 0,
  current_total: 0,
  rate_bytes_per_second: 100,
  eta_seconds: 6,
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
  created_at: null,
  started_at: null,
  finished_at: null,
  updated_at: null,
  ...over,
})

let transfers: ReturnType<typeof transfer>[]
let calls: { method: string; path: string; body?: unknown }[]

beforeEach(() => {
  calls = []
  transfers = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path: url.pathname, body })
      const p = url.pathname
      // The Tasks tab also lists exports and the saved filters they start from.
      if (p === '/api/file-access/exports' || p === '/api/views')
        return json([])
      if (p === '/api/store/volumes') return json([volume('a'), volume('b')])
      if (p === '/api/collections') return json([])
      if (p === '/api/settings/ui') return json({ show_advanced: false })
      if (p === '/api/store/transfers/preview')
        return json({
          files: 12,
          bytes: 3 * GB,
          already_there: 0,
          copied: 0,
          copied_bytes: 0,
          targets: [],
          problems: [],
          warnings: [],
          can_proceed: true,
        })
      if (p === '/api/store/transfers' && method === 'GET')
        return json(transfers)
      if (p === '/api/store/transfers' && method === 'POST')
        return json(transfer(), 202)
      if (p.endsWith('/pause')) return json(transfer({ control: 'pause' }))
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderTab(preset?: { source?: string }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <TasksTab preset={preset} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Tasks page', () => {
  it('shows an empty state when nothing has been moved', async () => {
    renderTab()
    expect(await screen.findByText(/No moves yet/)).toBeInTheDocument()
  })

  it('shows progress for a running transfer and pauses it', async () => {
    transfers = [transfer()]
    renderTab()
    expect(await screen.findByText(/Empty a onto b/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute(
      'aria-valuenow',
      '40',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.path.endsWith('/t1/pause')),
      ).toBe(true),
    )
  })

  it('shows a waiting move with its place in the queue, and can pause or cancel it', async () => {
    transfers = [
      transfer({ id: 't1' }),
      transfer({
        id: 't2',
        status: 'queued',
        live: false,
        created_at: '2026-10-04T10:00:00Z',
        progress: progress({ files_done: 0, bytes_done: 0 }),
      }),
    ]
    renderTab()
    expect(
      await screen.findByText(/starts after 1 other move/),
    ).toBeInTheDocument()
    expect(screen.getByText('Waiting')).toBeInTheDocument()
    // The running one and the waiting one can each be paused and cancelled.
    expect(screen.getAllByRole('button', { name: 'Pause' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(2)
  })

  it('says a new move joins the queue when another is running', async () => {
    transfers = [transfer()]
    renderTab({ source: 'a' })
    expect(
      await screen.findByRole('button', { name: 'Add to queue' }),
    ).toBeInTheDocument()
  })

  it('offers to resume an interrupted transfer, reassuringly', async () => {
    transfers = [transfer({ status: 'interrupted', live: false })]
    renderTab()
    expect(await screen.findByText(/Nothing was lost/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument()
  })

  it('lists files that could not be moved', async () => {
    transfers = [
      transfer({
        status: 'completed',
        failures_total: 1,
        failures: [{ sha256: 'ab'.repeat(32), volume: 'a', reason: 'corrupt' }],
      }),
    ]
    renderTab()
    expect(
      await screen.findByText(/1 file\(s\) could not be moved/),
    ).toBeInTheDocument()
  })

  it('previews a move before it can be started', async () => {
    renderTab({ source: 'a' })
    const start = await screen.findByRole('button', { name: 'Start moving' })
    expect(start).toBeDisabled()
    await userEvent.selectOptions(
      await screen.findByLabelText(/Put the files on/),
      'b',
    )
    expect(await screen.findByText(/12 files/)).toBeInTheDocument()
    await waitFor(() => expect(start).toBeEnabled())
    await userEvent.click(start)
    await waitFor(() =>
      expect(
        calls.find(
          (c) => c.method === 'POST' && c.path === '/api/store/transfers',
        )?.body,
      ).toMatchObject({ kind: 'drain', sources: ['a'], targets: ['b'] }),
    )
  })

  it('offers every volume as a target when gathering a collection', async () => {
    renderTab({ source: 'a' })
    await userEvent.click(await screen.findByLabelText('Gather a collection'))
    const target = await screen.findByLabelText(/Put the files on/)
    await waitFor(() =>
      expect(
        Array.from((target as HTMLSelectElement).options).map((o) => o.value),
      ).toEqual(['', 'a', 'b']),
    )
  })
})
