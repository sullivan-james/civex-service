import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '../../ui/ToastProvider'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
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
  ...over,
})

const collection = (id: string, name: string, records = 0) => ({
  id,
  name,
  description: null,
  timezone: null,
  record_count: records,
  deleted_at: null,
  scope: 'local',
  schemas: [],
})

type Call = { method: string; path: string; body?: unknown }
let volumes: ReturnType<typeof volume>[]
let placements: {
  collection_id: string
  collection_name: string | null
  volume: string
  on_unavailable: string
}[]
let calls: Call[]

beforeEach(() => {
  calls = []
  volumes = [
    volume('default', {
      path: '_civex/objects',
      in_queue: true,
      civex_used_bytes: GB,
    }),
    volume('archive', { in_queue: true, civex_used_bytes: 50 * GB }),
    volume('scratch'),
    volume('nas', {
      path: '/mnt/nas/civex',
      network: true,
      available: false,
      state: 'offline',
      reason: 'path missing: /mnt/nas/civex',
      fix: "Plug the drive in, or change the volume's path.",
      civex_used_bytes: null,
      disk_free_bytes: null,
      disk_total_bytes: null,
    }),
    volume('usb', {
      available: false,
      state: 'wrong_drive',
      reason: "expected volume 'usb' at /media/usb, found no volume marker",
      fix: 'Plug in the right drive.',
      civex_used_bytes: null,
      disk_free_bytes: null,
      disk_total_bytes: null,
    }),
  ]
  placements = [
    {
      collection_id: 'c1',
      collection_name: 'study',
      volume: 'archive',
      on_unavailable: 'spill',
    },
  ]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path: url.pathname + url.search, body })
      const p = url.pathname
      // The Tasks tab also lists exports and the saved filters they start from.
      if (p === '/api/file-access/exports' || p === '/api/views')
        return json([])

      if (p === '/api/store/volumes' && method === 'GET') return json(volumes)
      if (p === '/api/store/placement' && method === 'GET')
        return json(placements)
      if (p === '/api/store/transfers' && method === 'GET') return json([])
      if (p === '/api/store/collections' && method === 'GET') return json([])
      if (p === '/api/collections')
        return json([
          collection('c1', 'study', 120),
          collection('c2', 'field-notes', 3),
          collection('c3', 'zoo', 0),
        ])
      if (p === '/api/store/queue' && method === 'PUT') {
        const queue: string[] = body.queue
        volumes.forEach((v) => (v.in_queue = queue.includes(v.name)))
        volumes.sort((a, b) => {
          const ia = queue.indexOf(a.name)
          const ib = queue.indexOf(b.name)
          return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
        })
        return json(queue)
      }
      if (p.startsWith('/api/store/placement/')) {
        const id = p.split('/').pop()!
        placements = placements.filter((x) => x.collection_id !== id)
        if (method === 'PUT')
          placements.push({
            collection_id: id,
            collection_name: null,
            volume: body.volume,
            on_unavailable: body.on_unavailable ?? 'spill',
          })
        return method === 'DELETE'
          ? new Response(null, { status: 204 })
          : json({})
      }
      if (p.endsWith('/adopt')) return json({})
      if (p.startsWith('/api/store/volumes/'))
        return method === 'DELETE'
          ? new Response(null, { status: 204 })
          : json({})
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const loc = useLocation()
  return <p data-testid="where">{loc.pathname + loc.search}</p>
}

function renderAt(path = '/settings/storage') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/settings/storage" element={<StorageSettings />} />
          </Routes>
          <Where />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const volumeLink = (name: string) =>
  screen.getByRole('link', { name: new RegExp(`^${name}`) })
const rowOf = (name: string) => volumeLink(name).closest('tr') as HTMLElement

async function openMenu(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  await user.click(
    await screen.findByRole('button', { name: `Actions for ${name}` }),
  )
}

describe('Storage > Volumes', () => {
  it('shows one compact row per volume with its state and path', async () => {
    renderAt()

    await screen.findByRole('link', { name: /^archive/ })
    expect(within(rowOf('default')).getByText('Online')).toBeInTheDocument()
    expect(
      within(rowOf('archive')).getByText('/media/archive'),
    ).toBeInTheDocument()
    expect(
      within(rowOf('archive')).getByText('500 GB free of 1000 GB'),
    ).toBeInTheDocument()
    expect(
      within(rowOf('archive')).getByText('Civex uses 50.0 GB'),
    ).toBeInTheDocument()
    expect(within(rowOf('nas')).getByText('Network')).toBeInTheDocument()
    expect(within(rowOf('nas')).getByText('Offline')).toBeInTheDocument()
    expect(within(rowOf('usb')).getByText('Wrong drive')).toBeInTheDocument()
  })

  it('flags volumes that need attention and explains them in a tooltip', async () => {
    const user = userEvent.setup()
    renderAt()

    await screen.findByRole('link', { name: /^nas/ })
    const banner = screen.getByRole('alert')
    expect(banner).toHaveTextContent('2 volumes need attention: nas, usb')
    await user.click(
      within(rowOf('nas')).getByRole('button', { name: 'More information' }),
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'path missing: /mnt/nas/civex',
    )
  })

  it('links the whole row to the volume page and counts its collections', async () => {
    renderAt()

    await screen.findByRole('link', { name: /^archive/ })
    expect(volumeLink('archive')).toHaveAttribute(
      'href',
      '/settings/storage/volumes/archive',
    )
    expect(within(rowOf('archive')).getByText('1')).toBeInTheDocument()
    expect(within(rowOf('default')).getByText('—')).toBeInTheDocument()
  })

  it('reorders the write order', async () => {
    const user = userEvent.setup()
    renderAt()
    await screen.findByRole('link', { name: /^archive/ })

    const order = screen.getByRole('list', { name: 'Write order' })
    expect(within(order).getByText('default')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Move default down' }))

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/store/queue',
        body: { queue: ['archive', 'default'] },
      }),
    )
  })

  it('adds a volume to the write queue from its menu', async () => {
    const user = userEvent.setup()
    renderAt()
    await openMenu(user, 'scratch')

    await user.click(
      screen.getByRole('menuitem', { name: 'Add to write order' }),
    )

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/store/queue',
        body: { queue: ['default', 'archive', 'scratch'] },
      }),
    )
  })

  it('removes an unused volume with one click and says nothing is deleted', async () => {
    const user = userEvent.setup()
    renderAt()
    await openMenu(user, 'scratch')
    await user.click(screen.getByRole('menuitem', { name: 'Remove…' }))

    expect(
      await screen.findByRole('heading', { name: 'Remove volume “scratch”?' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Nothing is deleted from the drive.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Nothing uses it right now.')).toBeInTheDocument()
    expect(screen.queryByLabelText(/to confirm/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove volume' }))

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'DELETE',
        path: '/api/store/volumes/scratch',
        body: undefined,
      }),
    )
  })

  it('spells out what removing a volume holding files and homes would do', async () => {
    const user = userEvent.setup()
    renderAt()
    await openMenu(user, 'archive')
    await user.click(screen.getByRole('menuitem', { name: 'Remove…' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('It holds 50.0 GB of Civex files')
    expect(dialog).toHaveTextContent('1 collection uses it as its home')
    expect(dialog).toHaveTextContent('It leaves the write queue.')

    // Losing track of files takes a typed confirmation, then sends force.
    const remove = screen.getByRole('button', { name: 'Remove volume' })
    expect(remove).toBeDisabled()
    await user.type(screen.getByLabelText(/to confirm/), 'archive')
    expect(remove).toBeEnabled()
    await user.click(remove)

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'DELETE',
        path: '/api/store/volumes/archive?force=true',
        body: undefined,
      }),
    )
  })

  it('treats an unreachable volume as possibly holding files', async () => {
    const user = userEvent.setup()
    renderAt()
    await openMenu(user, 'nas')
    await user.click(screen.getByRole('menuitem', { name: 'Remove…' }))

    expect(await screen.findByRole('dialog')).toHaveTextContent(
      "Civex can't see what is on it right now",
    )
    expect(screen.getByRole('button', { name: 'Remove volume' })).toBeDisabled()
  })

  it('edits a volume’s space limit', async () => {
    const user = userEvent.setup()
    renderAt()
    await openMenu(user, 'archive')
    await user.click(screen.getByRole('menuitem', { name: 'Edit…' }))

    expect(
      await screen.findByRole('heading', { name: 'Edit volume “archive”' }),
    ).toBeInTheDocument()
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled()
    await user.click(
      screen.getByLabelText('Limit how much space Civex may use'),
    )
    await user.type(screen.getByLabelText('Space limit in GB'), '200')
    await user.click(save)

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PATCH',
        path: '/api/store/volumes/archive',
        body: { allocated_gb: 200 },
      }),
    )
  })

  it('confirms before treating a wrong drive as the volume', async () => {
    const user = userEvent.setup()
    renderAt()
    await screen.findByRole('link', { name: /^usb/ })

    await openMenu(user, 'usb')
    await user.click(
      screen.getByRole('menuitem', { name: 'This is the right drive…' }),
    )
    expect(
      await screen.findByRole('heading', {
        name: 'Treat this drive as “usb”?',
      }),
    ).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/adopt'))).toBe(false)
    await user.click(
      screen.getByRole('button', { name: 'Yes, this is the drive' }),
    )

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/store/volumes/usb/adopt',
        body: {},
      }),
    )
  })

  it('opens the add-volume dialog', async () => {
    const user = userEvent.setup()
    renderAt()

    await user.click(await screen.findByRole('button', { name: 'Add volume' }))

    expect(
      await screen.findByRole('heading', { name: 'Add a volume' }),
    ).toBeInTheDocument()
  })
})

describe('Storage > Collections', () => {
  it('lists every collection with its home, and can be linked to', async () => {
    renderAt('/settings/storage?tab=collections')

    const study = await screen.findByLabelText('Home volume for study')
    expect(study).toHaveValue('archive')
    expect(screen.getByLabelText('Home volume for field-notes')).toHaveValue('')
    expect(screen.getByLabelText('Home volume for zoo')).toHaveValue('')
    expect(screen.getByRole('link', { name: /^study/ })).toHaveAttribute(
      'href',
      '/collections/c1',
    )
    expect(screen.getByText('120 records')).toBeInTheDocument()
  })

  it('assigns a home as soon as it is chosen', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections')

    await user.selectOptions(
      await screen.findByLabelText('Home volume for zoo'),
      'scratch',
    )

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/store/placement/c3',
        body: { volume: 'scratch', on_unavailable: 'spill' },
      }),
    )
  })

  it('clears a home by choosing the write queue', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections')

    await user.selectOptions(
      await screen.findByLabelText('Home volume for study'),
      '',
    )

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'DELETE',
        path: '/api/store/placement/c1',
        body: undefined,
      }),
    )
  })

  it('changes what happens when the home is unavailable', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections')

    await user.selectOptions(
      await screen.findByLabelText(
        "If the home volume of study can't take a file",
      ),
      'fail',
    )

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/store/placement/c1',
        body: { volume: 'archive', on_unavailable: 'fail' },
      }),
    )
    // A collection with no home has nothing to choose.
    expect(
      screen.queryByLabelText("If the home volume of zoo can't take a file"),
    ).not.toBeInTheDocument()
  })

  it('assigns several collections at once', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections')
    await user.click(await screen.findByLabelText('Select field-notes'))
    await user.click(screen.getByLabelText('Select zoo'))

    const bar = screen.getByRole('region', { name: 'Bulk actions' })
    expect(bar).toHaveTextContent('2 selected')
    await user.selectOptions(
      within(bar).getByLabelText('Home volume for the selected collections'),
      'scratch',
    )
    await user.click(within(bar).getByRole('button', { name: 'Apply' }))

    await waitFor(() => {
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/store/placement/c2',
        body: { volume: 'scratch', on_unavailable: 'spill' },
      })
      expect(calls).toContainEqual({
        method: 'PUT',
        path: '/api/store/placement/c3',
        body: { volume: 'scratch', on_unavailable: 'spill' },
      })
    })
    await waitFor(() =>
      expect(
        screen.queryByRole('region', { name: 'Bulk actions' }),
      ).not.toBeInTheDocument(),
    )
  })

  it('filters by name and by home volume', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections&volume=archive')

    await screen.findByLabelText('Home volume for study')
    expect(
      screen.queryByLabelText('Home volume for zoo'),
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /On archive/ }))
    expect(
      await screen.findByLabelText('Home volume for zoo'),
    ).toBeInTheDocument()

    await user.type(screen.getByLabelText('Filter collections'), 'note')
    expect(
      screen.queryByLabelText('Home volume for zoo'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByLabelText('Home volume for field-notes'),
    ).toBeInTheDocument()
  })

  it('opens on the collection a link from its own page pointed at', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections&focus=c1')

    // Only that collection's row, with a way to see them all.
    expect(
      await screen.findByLabelText('Home volume for study'),
    ).toBeInTheDocument()
    expect(
      screen.queryByLabelText('Home volume for zoo'),
    ).not.toBeInTheDocument()
    expect(screen.getByLabelText('Filter collections')).toHaveValue('study')

    await user.clear(screen.getByLabelText('Filter collections'))
    expect(
      await screen.findByLabelText('Home volume for zoo'),
    ).toBeInTheDocument()
  })

  it('forgets the focused collection when leaving the Collections tab', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections&focus=c1')
    await screen.findByLabelText('Home volume for study')

    await user.click(screen.getByRole('tab', { name: 'Tasks' }))

    expect(screen.getByTestId('where')).toHaveTextContent('?tab=tasks')
    expect(screen.getByTestId('where')).not.toHaveTextContent('focus')
  })

  it('marks a collection whose home is offline', async () => {
    placements = [
      {
        collection_id: 'c3',
        collection_name: 'zoo',
        volume: 'nas',
        on_unavailable: 'spill',
      },
    ]
    renderAt('/settings/storage?tab=collections')

    await screen.findByLabelText('Home volume for zoo')
    expect(screen.getByText('Home offline')).toBeInTheDocument()
    // An offline volume stays choosable, but is labelled in every row's list.
    expect(
      screen.getAllByRole('option', { name: 'nas (offline)' }).length,
    ).toBeGreaterThan(0)
  })

  it('points a single-volume project at adding another', async () => {
    volumes = [volume('default', { in_queue: true })]
    placements = []
    const user = userEvent.setup()
    renderAt('/settings/storage?tab=collections')

    expect(await screen.findByText(/One volume/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add a volume' }))

    expect(screen.getByTestId('where')).toHaveTextContent('/settings/storage')
    expect(
      await screen.findByRole('button', { name: 'Add volume' }),
    ).toBeInTheDocument()
  })
})

describe('Storage tabs', () => {
  it('opens on Volumes and keeps the tab in the address', async () => {
    const user = userEvent.setup()
    renderAt()

    expect(await screen.findByRole('tab', { name: 'Volumes' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await user.click(screen.getByRole('tab', { name: 'Collections' }))
    expect(screen.getByTestId('where')).toHaveTextContent('?tab=collections')
    expect(
      await screen.findByLabelText('Home volume for study'),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Tasks' }))
    expect(screen.getByTestId('where')).toHaveTextContent('?tab=tasks')
    expect(screen.getByRole('tabpanel')).toHaveAttribute(
      'aria-labelledby',
      'tab-tasks',
    )

    await user.click(screen.getByRole('tab', { name: 'Volumes' }))
    expect(screen.getByTestId('where')).toHaveTextContent(
      /^\/settings\/storage$/,
    )
  })

  it('ignores an unknown tab name', async () => {
    renderAt('/settings/storage?tab=nonsense')

    expect(await screen.findByRole('tab', { name: 'Volumes' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })
})
