import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CollectionStorage } from './CollectionStorage'

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

beforeEach(() => {
  volumes = [volume('default'), volume('archive')]
  placements = []
  calls = []
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
      <CollectionStorage collectionId={CID} />
    </QueryClientProvider>,
  )
}

describe('CollectionStorage', () => {
  it('shows nothing on a single-volume project', async () => {
    volumes = [volume('default')]
    const { container } = renderIt()
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/store/volumes')).toBe(true),
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('sets a home volume', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /storage/i }))

    const [home] = screen.getAllByRole('combobox')
    await user.selectOptions(home, 'archive')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: `/api/store/placement/${CID}`,
        body: { volume: 'archive', on_unavailable: 'spill' },
      }),
    )
  })

  it('can refuse uploads instead of spilling', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /storage/i }))
    const [home] = screen.getAllByRole('combobox')
    await user.selectOptions(home, 'archive')
    const [, policy] = screen.getAllByRole('combobox')
    await user.selectOptions(policy, 'fail')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'PUT',
        path: `/api/store/placement/${CID}`,
        body: { volume: 'archive', on_unavailable: 'fail' },
      }),
    )
  })

  it('opens by default when a home is set, and clears it', async () => {
    placements = [
      {
        collection_id: CID,
        collection_name: 'study',
        volume: 'archive',
        on_unavailable: 'spill',
      },
    ]
    const user = userEvent.setup()
    renderIt()

    const save = await screen.findByRole('button', { name: 'Save' })
    expect(save).toBeDisabled()
    const [home] = screen.getAllByRole('combobox')
    expect(home).toHaveValue('archive')

    await user.selectOptions(home, '')
    await user.click(save)

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'DELETE',
        path: `/api/store/placement/${CID}`,
        body: undefined,
      }),
    )
  })

  it('warns when the home volume is offline, with the reason', async () => {
    volumes = [
      volume('default'),
      volume('archive', {
        state: 'offline',
        available: false,
        reason: 'path missing: /mnt/archive',
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
      await screen.findByText('path missing: /mnt/archive'),
    ).toBeInTheDocument()
  })
})
