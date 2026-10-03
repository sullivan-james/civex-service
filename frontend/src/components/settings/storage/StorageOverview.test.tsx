import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import StorageSettings from './StorageSettings'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const GB = 1024 ** 3
const volume = (name: string, over: Record<string, unknown> = {}) => ({
  name,
  path: `/media/${name}`,
  allocated_gb: null,
  civex_used_bytes: GB,
  disk_free_bytes: 500 * GB,
  disk_total_bytes: 1000 * GB,
  available: true,
  state: 'online',
  reason: '',
  fix: '',
  warning: false,
  in_queue: false,
  network: false,
  ...over,
})

const share = (v: string, files: number, bytes: number, state = 'online') => ({
  volume: v,
  files,
  bytes,
  shared_files: 0,
  state,
  available: state === 'online',
})

let volumes: ReturnType<typeof volume>[]
let transfers: Record<string, unknown>[]
let spreads: Record<string, unknown>[]

beforeEach(() => {
  volumes = [volume('default'), volume('archive')]
  transfers = []
  spreads = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const p = new URL(String(input), 'http://x').pathname
      const method = init?.method ?? 'GET'
      if (p === '/api/store/volumes') return json(volumes)
      if (p === '/api/store/placement') return json([])
      if (p === '/api/store/transfers' && method === 'GET')
        return json(transfers)
      if (p === '/api/store/collections') return json(spreads)
      if (p === '/api/collections')
        return json([
          {
            id: 'c1',
            name: 'study',
            description: null,
            timezone: null,
            record_count: 5,
            deleted_at: null,
            scope: 'local',
            schemas: [],
          },
        ])
      if (p === '/api/settings/ui') return json({ show_advanced: false })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderAt(url = '/settings/storage') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <StorageSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const running = {
  id: 't1',
  kind: 'drain',
  status: 'running',
  spec: {
    kind: 'drain',
    targets: ['archive'],
    sources: ['default'],
    collection_ids: [],
    include_shared: false,
    verify: 'copy',
    freeze_sources: true,
  },
  plan: null,
  progress: {
    files_total: 10,
    files_done: 4,
    files_skipped: 0,
    files_failed: 0,
    bytes_total: 1000,
    bytes_done: 400,
    current: null,
    current_bytes: 0,
    current_total: 0,
    rate_bytes_per_second: 0,
    eta_seconds: null,
    message: '',
  },
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
}

describe('Storage page', () => {
  it('has three tabs: Volumes, Collections, Tasks', async () => {
    renderAt()
    const tabs = await screen.findAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual([
      'Volumes',
      'Collections',
      'Tasks',
    ])
  })

  it('says nothing when all is well', async () => {
    renderAt()
    await screen.findByRole('tab', { name: 'Volumes' })
    await waitFor(() =>
      expect(screen.queryByLabelText('Needs attention')).toBeNull(),
    )
  })

  it('flags an unplugged volume that holds files, and goes to it', async () => {
    volumes = [
      volume('default'),
      volume('usb', {
        available: false,
        state: 'offline',
        reason: 'path missing: /media/usb',
      }),
    ]
    renderAt('/settings/storage?tab=tasks')
    const alert = await screen.findByLabelText('Needs attention')
    expect(alert).toHaveTextContent('usb: path missing: /media/usb')
    await userEvent.click(screen.getByRole('button', { name: 'Open Volumes' }))
    expect(screen.getByRole('tab', { name: 'Volumes' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('stays quiet about an unplugged volume that holds nothing', async () => {
    volumes = [
      volume('default'),
      volume('usb', {
        available: false,
        state: 'offline',
        civex_used_bytes: 0,
      }),
    ]
    renderAt()
    await screen.findByRole('tab', { name: 'Volumes' })
    await waitFor(() =>
      expect(screen.queryByLabelText('Needs attention')).toBeNull(),
    )
  })

  it('shows a running move and an interrupted one', async () => {
    transfers = [running, { ...running, id: 't2', status: 'interrupted' }]
    renderAt()
    const alert = await screen.findByLabelText('Needs attention')
    expect(alert).toHaveTextContent('Moving files: 4 of 10 done.')
    expect(alert).toHaveTextContent('A move was interrupted')
  })

  it.each(['transfers', 'maintenance'])(
    'still opens Tasks from an old ?tab=%s address',
    async (old) => {
      renderAt(`/settings/storage?tab=${old}`)
      expect(await screen.findByRole('tab', { name: 'Tasks' })).toHaveAttribute(
        'aria-selected',
        'true',
      )
      expect(
        await screen.findByRole('heading', { name: 'Move files' }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('heading', { name: 'Clean up unused files' }),
      ).toBeInTheDocument()
    },
  )

  it("shows where each collection's files are, and offers to gather them", async () => {
    spreads = [
      {
        collection_id: 'c1',
        files: 12,
        bytes: 3 * GB,
        unlocated_files: 0,
        volumes: [share('archive', 9, 2 * GB), share('default', 3, GB)],
      },
    ]
    renderAt('/settings/storage?tab=collections')
    await waitFor(() =>
      expect(document.body.textContent).toContain(
        'archive 2.0 GB · default 1.0 GB',
      ),
    )
    expect(
      screen.getByRole('button', { name: /Gather 3 files onto archive/ }),
    ).toBeInTheDocument()
  })

  describe('inspecting a drive', () => {
    const report = (id: string, vols: [string, number][]) => ({
      collection_id: id,
      files: 3,
      bytes: vols.reduce((n, [, b]) => n + b, 0),
      unlocated_files: 0,
      volumes: vols.map(([v, b]) => share(v, 1, b)),
    })

    it('explains what part of a volume is unused', async () => {
      volumes = [
        volume('default', {
          civex_used_bytes: 442 * 1024 ** 2,
          unused_files: 4,
          unused_bytes: 439 * 1024 ** 2,
          history_files: 10,
          history_bytes: 3 * 1024 ** 2,
        }),
      ]
      renderAt()
      expect(
        await screen.findByText(/439 MB of it is unused/),
      ).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'Clean up' })).toHaveAttribute(
        'href',
        '/settings/storage?tab=tasks',
      )
      expect(
        screen.getByText(/3\.0 MB is kept only for workflow history/),
      ).toBeInTheDocument()
    })

    it('says nothing about unused files when there are none', async () => {
      renderAt()
      await screen.findByText('archive')
      expect(screen.queryByText(/is unused/)).toBeNull()
    })

    it('counts the collections that have files on a drive', async () => {
      spreads = [
        report('c1', [['archive', GB]]),
        report('c2', [
          ['archive', GB],
          ['default', GB],
        ]),
        report('c3', [['default', GB]]),
      ]
      renderAt()
      const links = await screen.findAllByRole('link', {
        name: /collections?$/,
      })
      const byVolume = Object.fromEntries(
        links.map((l) => [
          new URL(l.getAttribute('href') ?? '', 'http://x').searchParams.get(
            'volume',
          ),
          l.textContent,
        ]),
      )
      expect(byVolume).toEqual({
        archive: '2 collections',
        default: '2 collections',
      })
    })

    it('lists the collections on a drive, picking out its share', async () => {
      spreads = [
        report('c1', [['archive', GB]]),
        report('c9', [['default', GB]]), // not on archive
      ]
      renderAt('/settings/storage?tab=collections&volume=archive')
      expect(await screen.findByText('study')).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /On archive/ }),
      ).toBeInTheDocument()
      expect(screen.getByText('archive 1.0 GB')).toHaveClass('font-medium')
    })
  })
})
