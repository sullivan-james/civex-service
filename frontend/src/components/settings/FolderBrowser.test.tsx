import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FolderBrowser } from './FolderBrowser'
import { breadcrumbs } from '../../utils/storage'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const LOCATIONS = [
  {
    label: 'Project',
    path: '/work/proj',
    kind: 'project',
    free_bytes: 5e11,
    total_bytes: 1e12,
    network: false,
    source: null,
  },
  {
    label: 'Home',
    path: '/home/me',
    kind: 'home',
    free_bytes: 5e11,
    total_bytes: 1e12,
    network: false,
    source: null,
  },
  {
    label: 'usb',
    path: '/media/usb',
    kind: 'drive',
    free_bytes: 2 * 1024 ** 4,
    total_bytes: 4 * 1024 ** 4,
    network: false,
    source: null,
  },
  {
    label: 'nas',
    path: '/mnt/nas',
    kind: 'drive',
    free_bytes: null,
    total_bytes: null,
    network: true,
    source: 'nas.local:/export',
  },
]

let fs: Record<string, string[]>
let calls: { method: string; path: string; body?: unknown }[]

const dirname = (p: string) => p.replace(/\/[^/]+$/, '') || '/'

beforeEach(() => {
  fs = {
    '/': ['home', 'mnt'],
    '/home/me': ['archive', 'docs'],
    '/home/me/archive': ['2025'],
    '/media/usb': [],
    '/mnt/nas': ['backups'],
  }
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: url.pathname + url.search,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (url.pathname === '/api/store/browse/folder' && method === 'POST') {
        const { parent, name } = JSON.parse(String(init?.body))
        const made = `${parent}/${name}`
        fs[made] = []
        fs[parent] = [...fs[parent], name]
        return json({ path: made }, 201)
      }
      if (url.pathname === '/api/store/browse') {
        const path = url.searchParams.get('path') ?? '/home/me'
        if (!(path in fs))
          return json({ detail: `Folder '${path}' not found` }, 404)
        return json({
          path,
          parent: path === '/' ? null : dirname(path),
          entries: fs[path].map((name) => ({
            name,
            path: `${path === '/' ? '' : path}/${name}`,
          })),
          truncated: false,
          locations: LOCATIONS,
        })
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(props: Partial<Parameters<typeof FolderBrowser>[0]> = {}) {
  const onSelect = vi.fn()
  const onCancel = vi.fn()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <FolderBrowser onSelect={onSelect} onCancel={onCancel} {...props} />
    </QueryClientProvider>,
  )
  return { onSelect, onCancel }
}

describe('breadcrumbs', () => {
  it('splits a path into clickable steps', () => {
    expect(breadcrumbs('/home/me/data')).toEqual([
      { label: '/', path: '/' },
      { label: 'home', path: '/home' },
      { label: 'me', path: '/home/me' },
      { label: 'data', path: '/home/me/data' },
    ])
    expect(breadcrumbs('C:/Users/me')).toEqual([
      { label: 'C:', path: 'C:/' },
      { label: 'Users', path: 'C:/Users' },
      { label: 'me', path: 'C:/Users/me' },
    ])
  })
})

describe('FolderBrowser', () => {
  it('starts at home with places, drives and network drives marked', async () => {
    renderIt()

    expect(await screen.findByText('archive')).toBeInTheDocument()
    const places = screen.getByRole('navigation', { name: 'Places' })
    expect(within(places).getByText('Project')).toBeInTheDocument()
    expect(within(places).getByText('Home')).toBeInTheDocument()
    expect(
      within(places).getByText('2.0 TB free of 4.0 TB'),
    ).toBeInTheDocument()
    // A network drive shows where it really is, not a (slow) free-space read.
    expect(within(places).getByText('nas.local:/export')).toBeInTheDocument()
    expect(screen.getByText('Selected folder').nextSibling).toHaveTextContent(
      '/home/me',
    )
  })

  it('navigates into folders, up, and by breadcrumb', async () => {
    const user = userEvent.setup()
    const { onSelect } = renderIt()

    await user.click(await screen.findByRole('button', { name: /archive/ }))
    expect(await screen.findByText('2025')).toBeInTheDocument()
    expect(screen.getByLabelText('Current folder')).toHaveTextContent('archive')

    await user.click(screen.getByRole('button', { name: 'Up one folder' }))
    expect(await screen.findByText('docs')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Choose this folder' }))
    expect(onSelect).toHaveBeenCalledWith('/home/me')
  })

  it('jumps to a drive, including a network drive', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('archive')

    await user.click(screen.getByRole('button', { name: /nas/ }))

    expect(await screen.findByText('backups')).toBeInTheDocument()
    expect(
      calls.some((c) => c.path === '/api/store/browse?path=%2Fmnt%2Fnas'),
    ).toBe(true)
  })

  it('creates a folder and opens it', async () => {
    const user = userEvent.setup()
    const { onSelect } = renderIt()
    await screen.findByText('archive')

    await user.click(screen.getByRole('button', { name: /new folder/i }))
    await user.type(screen.getByLabelText('New folder name'), 'civex-data')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/store/browse/folder',
        body: { parent: '/home/me', name: 'civex-data' },
      }),
    )
    await waitFor(() =>
      expect(screen.getByText('Selected folder').nextSibling).toHaveTextContent(
        '/home/me/civex-data',
      ),
    )
    await user.click(screen.getByRole('button', { name: 'Choose this folder' }))
    expect(onSelect).toHaveBeenCalledWith('/home/me/civex-data')
  })

  it('falls back to home when the starting folder is not there', async () => {
    renderIt({ initialPath: '/gone/drive' })

    expect(await screen.findByText('archive')).toBeInTheDocument()
    expect(calls[0].path).toBe('/api/store/browse?path=%2Fgone%2Fdrive')
    expect(calls[calls.length - 1]?.path).toBe('/api/store/browse')
  })

  it('cancels', async () => {
    const user = userEvent.setup()
    const { onCancel } = renderIt()
    await screen.findByText('archive')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onCancel).toHaveBeenCalled()
  })
})
