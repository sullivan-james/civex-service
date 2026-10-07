import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import VolumePage from './VolumePage'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const MB = 1024 ** 2
const volume = (name: string, over: Record<string, unknown> = {}) => ({
  name,
  path: `/media/${name}`,
  allocated_gb: null,
  civex_used_bytes: 442 * MB,
  disk_free_bytes: 500 * 1024 * MB,
  disk_total_bytes: 1000 * 1024 * MB,
  available: true,
  state: 'online',
  reason: '',
  fix: '',
  warning: false,
  in_queue: false,
  network: false,
  unused_files: 0,
  unused_bytes: 0,
  history_files: 0,
  history_bytes: 0,
  ...over,
})

const share = (v: string, files: number, bytes: number, shared = 0) => ({
  volume: v,
  files,
  bytes,
  shared_files: shared,
  state: 'online',
  available: true,
})

let volumes: ReturnType<typeof volume>[]
let spreads: Record<string, unknown>[]
let placements: Record<string, unknown>[]
let transfers: Record<string, unknown>[]
let calls: { method: string; path: string; body?: unknown }[]

beforeEach(() => {
  calls = []
  volumes = [
    volume('default', {
      in_queue: true,
      unused_files: 4,
      unused_bytes: 439 * MB,
      history_files: 10,
      history_bytes: 3 * MB,
    }),
    volume('archive'),
  ]
  spreads = [
    {
      collection_id: 'c1',
      files: 12,
      bytes: 300 * MB,
      unlocated_files: 0,
      volumes: [
        share('default', 9, 200 * MB, 2),
        share('archive', 3, 100 * MB),
      ],
    },
    {
      collection_id: 'c2',
      files: 1,
      bytes: 5 * MB,
      unlocated_files: 0,
      volumes: [share('archive', 1, 5 * MB)],
    },
  ]
  placements = []
  transfers = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const p = new URL(String(input), 'http://x').pathname
      // The Tasks tab also lists exports and the saved filters they start from.
      if (p === '/api/file-access/exports' || p === '/api/views')
        return json([])
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: p,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (p === '/api/store/volumes') return json(volumes)
      if (p === '/api/store/placement') return json(placements)
      if (p === '/api/store/collections') return json(spreads)
      if (p === '/api/store/transfers' && method === 'GET')
        return json(transfers)
      if (p === '/api/collections')
        return json(
          [
            ['c1', 'study'],
            ['c2', 'field-notes'],
          ].map(([id, name]) => ({
            id,
            name,
            description: null,
            timezone: null,
            record_count: 1,
            deleted_at: null,
            scope: 'local',
            schemas: [],
          })),
        )
      if (p === '/api/settings/ui') return json({ show_advanced: false })
      if (p === '/api/store/gc')
        return json({
          dry_run: true,
          grace_days: 14,
          scanned: 0,
          referenced: 0,
          protected_by_grace: 0,
          deleted_count: 0,
          deleted_bytes: 0,
          deleted: [],
          stale_scratch_removed: 0,
        })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderAt(name: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/settings/storage/volumes/${name}`]}>
        <Routes>
          <Route
            path="/settings/storage/volumes/:name"
            element={<VolumePage />}
          />
          <Route path="/settings/storage" element={<p>the storage page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const openActions = async () =>
  userEvent.click(await screen.findByRole('button', { name: 'More actions' }))

describe('a volume’s page', () => {
  it('lists the collections on the drive, largest first, with their share', async () => {
    renderAt('default')
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('study')).toBeInTheDocument()
    expect(rows[0]).toHaveTextContent('9')
    expect(rows[0]).toHaveTextContent('200 MB')
    await userEvent.click(
      within(rows[0]).getByRole('button', { name: 'More information' }),
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      '2 files are also used by other collections',
    )
    // field-notes has nothing on default, so isn't listed here
    expect(within(table).queryByText('field-notes')).toBeNull()
  })

  it('explains what is unused and what only workflow history keeps', async () => {
    renderAt('default')
    const unused = (await screen.findByText('Unused')).closest('tr')!
    expect(unused).toHaveTextContent('439 MB')
    // It cleans up right here, on this volume, rather than sending you off to
    // find a panel on another page.
    expect(
      within(unused).getByRole('button', { name: 'Clean up…' }),
    ).toBeInTheDocument()
    expect(within(unused).queryByRole('link', { name: /Clean up/ })).toBeNull()
    const history = screen.getByText('Workflow run history').closest('tr')!
    expect(history).toHaveTextContent('3.0 MB')
  })

  it('cleans up from the volume page itself, limited to that volume', async () => {
    const user = userEvent.setup()
    renderAt('default')
    const unused = (await screen.findByText('Unused')).closest('tr')!

    await user.click(within(unused).getByRole('button', { name: 'Clean up…' }))

    expect(
      await screen.findByRole('heading', {
        name: 'Clean up unused files on default',
      }),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/api/store/gc')?.body).toMatchObject(
        { volume: 'default', apply: false },
      ),
    )
  })

  it('shows a collection homed here that has no files yet', async () => {
    placements = [
      {
        collection_id: 'c2',
        collection_name: 'field-notes',
        volume: 'default',
        on_unavailable: 'spill',
      },
    ]
    renderAt('default')
    const row = (await screen.findByText('field-notes')).closest('tr')!
    expect(row).toHaveTextContent('home')
    expect(within(row).queryByRole('button', { name: 'Move…' })).toBeNull()
  })

  it('says where the volume sits in the write queue', async () => {
    renderAt('default')
    expect(await screen.findByText('Write order #1')).toBeInTheDocument()
    await openActions()
    expect(
      screen.getByRole('menuitem', { name: 'Remove from write order' }),
    ).toBeInTheDocument()
  })

  it('adds an unqueued volume to the queue', async () => {
    renderAt('archive')
    await openActions()
    await userEvent.click(
      screen.getByRole('menuitem', { name: 'Add to write order' }),
    )
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/store/queue',
        body: { queue: ['default', 'archive'] },
      }),
    )
  })

  it('says what is wrong with an unplugged drive, and that the list is still complete', async () => {
    volumes = [
      volume('default'),
      volume('usb', {
        available: false,
        state: 'offline',
        reason: 'path missing: /media/usb',
        fix: 'Plug the drive in.',
      }),
    ]
    spreads = [
      {
        collection_id: 'c1',
        files: 3,
        bytes: 9 * MB,
        unlocated_files: 0,
        volumes: [
          { ...share('usb', 3, 9 * MB), state: 'offline', available: false },
        ],
      },
    ]
    renderAt('usb')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('path missing: /media/usb')
    await userEvent.click(
      within(alert).getByRole('button', { name: 'More information' }),
    )
    const tip = screen.getByRole('tooltip')
    expect(tip).toHaveTextContent('Plug the drive in.')
    expect(tip).toHaveTextContent('complete even while the drive is away')
    expect(await screen.findByText('study')).toBeInTheDocument()
    // moving files off a drive that can't be read isn't offered
    await openActions()
    expect(
      screen.queryByRole('menuitem', { name: /Move everything off/ }),
    ).toBeNull()
  })

  it('starts a move off the drive from its page', async () => {
    renderAt('default')
    await openActions()
    await userEvent.click(
      screen.getByRole('menuitem', { name: 'Move everything off…' }),
    )
    expect(await screen.findByLabelText(/Move everything off/)).toHaveValue(
      'default',
    )
  })

  it('shows the moves that involve the drive, and only those', async () => {
    const t = (id: string, sources: string[], targets: string[]) => ({
      id,
      kind: 'drain',
      status: 'completed',
      spec: {
        kind: 'drain',
        targets,
        sources,
        collection_ids: [],
        verify: 'copy',
        freeze_sources: true,
      },
      plan: null,
      progress: {
        files_total: 1,
        files_done: 1,
        files_skipped: 0,
        files_failed: 0,
        bytes_total: 1,
        bytes_done: 1,
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
      live: false,
      created_at: null,
      started_at: null,
      finished_at: null,
      updated_at: null,
    })
    transfers = [t('t1', ['default'], ['archive']), t('t2', ['x'], ['y'])]
    renderAt('archive')
    await userEvent.click(await screen.findByRole('tab', { name: /Moves/ }))
    expect(
      await screen.findByText('Empty default onto archive'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Empty x onto y')).toBeNull()
  })

  it('says so when there is no such volume', async () => {
    renderAt('ghost')
    expect(
      await screen.findByText(/No volume called “ghost”/),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Storage/ })).toHaveAttribute(
      'href',
      '/settings/storage',
    )
  })
})
