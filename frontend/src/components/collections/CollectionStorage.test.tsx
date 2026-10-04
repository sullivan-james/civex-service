import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { CollectionStorage, useHasStorageChoice } from './CollectionStorage'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const volume = (name: string, over: Record<string, unknown> = {}) => ({
  name,
  path: `/mnt/${name}`,
  allocated_gb: null,
  civex_used_bytes: 0,
  disk_free_bytes: 1e12,
  disk_total_bytes: 2e12,
  available: true,
  state: 'online',
  reason: '',
  fix: '',
  warning: false,
  in_queue: false,
  ...over,
})

const CID = '3f2b8c1e-0000-4000-8000-123456789abc'

let volumes: ReturnType<typeof volume>[]
let placements: Record<string, unknown>[]
let calls: { method: string; path: string; body: unknown }[]
let spread: Record<string, unknown>

beforeEach(() => {
  volumes = [volume('default'), volume('archive')]
  placements = []
  calls = []
  spread = {
    collection_id: CID,
    files: 0,
    bytes: 0,
    volumes: [],
    unlocated_files: 0,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: url.pathname,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (url.pathname === '/api/store/volumes') return json(volumes)
      if (url.pathname === `/api/store/collections/${CID}`) return json(spread)
      if (url.pathname === '/api/store/placement' && method === 'GET')
        return json(placements)
      if (url.pathname.startsWith('/api/store/placement/')) {
        if (method === 'DELETE') return new Response(null, { status: 204 })
        return json({
          collection_id: CID,
          collection_name: 'study',
          ...(init?.body ? JSON.parse(String(init.body)) : {}),
        })
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CollectionStorage collectionId={CID} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CollectionStorage', () => {
  it('is only worth a tab once there is a choice to make', async () => {
    function Probe() {
      return <p>{useHasStorageChoice(CID) ? 'choice' : 'no choice'}</p>
    }
    volumes = [volume('default')]
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/store/volumes')).toBe(true),
    )
    expect(screen.getByText('no choice')).toBeInTheDocument()
  })

  it('says where new files go when there is no home volume', async () => {
    renderIt()

    const section = await screen.findByRole('region', {
      name: 'Where new files go',
    })
    expect(section).toHaveTextContent("Wherever there's room")
    expect(section).toHaveTextContent('no home volume')
  })

  it('says which volume is home, whether it is up, and what happens when it is full', async () => {
    placements = [
      {
        collection_id: CID,
        collection_name: 'study',
        volume: 'archive',
        on_unavailable: 'fail',
      },
    ]
    renderIt()

    const section = await screen.findByRole('region', {
      name: 'Where new files go',
    })
    await waitFor(() => expect(section).toHaveTextContent('(online)'))
    expect(section).toHaveTextContent('To archive')
    expect(section).toHaveTextContent('the upload is refused')
  })

  it('does not edit anything here: changing it is a link into Settings', async () => {
    renderIt()

    const link = await screen.findByRole('link', {
      name: 'Change where new files go',
    })
    expect(link).toHaveAttribute(
      'href',
      `/settings/storage?tab=collections&focus=${CID}`,
    )
    // One place to change a home, so there is nothing to set or save here.
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
    expect(
      calls.filter((c) => c.method === 'PUT' || c.method === 'DELETE'),
    ).toEqual([])
  })

  it('warns when the home volume is offline, with the reason and what to do', async () => {
    volumes = [
      volume('default'),
      volume('archive', {
        state: 'offline',
        available: false,
        reason: 'path missing: /mnt/archive',
        fix: "Plug in the drive for 'archive'.",
      }),
    ]
    placements = [
      {
        collection_id: CID,
        collection_name: 'study',
        volume: 'archive',
        on_unavailable: 'spill',
      },
    ]
    renderIt()

    expect(
      await screen.findByText(
        /path missing: \/mnt\/archive Plug in the drive for 'archive'\./,
      ),
    ).toBeInTheDocument()
  })

  describe('where the files are', () => {
    const split = (over: Record<string, unknown> = {}) => ({
      collection_id: CID,
      files: 12,
      bytes: 3e9,
      unlocated_files: 0,
      volumes: [
        {
          volume: 'archive',
          files: 9,
          bytes: 2.5e9,
          shared_files: 0,
          state: 'online',
          available: true,
        },
        {
          volume: 'usb',
          files: 3,
          bytes: 5e8,
          shared_files: 2,
          state: 'offline',
          available: false,
        },
      ],
      ...over,
    })

    it('lists each volume when files are split', async () => {
      spread = split()
      renderIt()
      const block = await screen.findByTestId('file-locations')
      expect(block).toHaveTextContent('12 files')
      expect(block).toHaveTextContent('on 2 volumes')
      expect(block).toHaveTextContent('archive')
      expect(block).toHaveTextContent('3 files')
      expect(block).toHaveTextContent('2 also used by other collections')
      // a volume that is unplugged says its files can't be opened
      expect(block).toHaveTextContent(/can.t be opened right now/)
    })

    it('tells a person which drive to plug in for files that are out of reach', async () => {
      volumes = [
        volume('default'),
        volume('usb', {
          state: 'offline',
          available: false,
          fix: "Plug in the drive for 'usb'.",
        }),
      ]
      spread = split()
      renderIt()

      const block = await screen.findByTestId('file-locations')
      await waitFor(() =>
        expect(block).toHaveTextContent("Plug in the drive for 'usb'."),
      )
    })

    it('links to gather in Settings, where moves are managed', async () => {
      spread = split()
      placements = [
        {
          collection_id: CID,
          collection_name: 'study',
          volume: 'archive',
          on_unavailable: 'spill',
        },
      ]
      renderIt()
      expect(
        await screen.findByRole('link', { name: /Gather onto archive/ }),
      ).toHaveAttribute(
        'href',
        `/settings/storage?tab=tasks&collection=${CID}&to=archive`,
      )
    })

    it('has nothing to gather when everything is on one volume', async () => {
      spread = split({
        volumes: [split().volumes[0]],
        files: 9,
      })
      placements = [
        {
          collection_id: CID,
          collection_name: 'study',
          volume: 'archive',
          on_unavailable: 'spill',
        },
      ]
      renderIt()
      expect(await screen.findByTestId('file-locations')).toHaveTextContent(
        'on one volume',
      )
      expect(screen.queryByRole('link', { name: /Gather/ })).toBeNull()
    })
  })
})
