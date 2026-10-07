import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui'
import { FilesView } from './FilesView'
import { fakeServer } from './testSupport'

afterEach(() => vi.unstubAllGlobals())

const file = (over: Record<string, unknown>) => ({
  path: 'Encounter 7/s1/table.txt',
  sha256: 'aaa',
  filename: 'table.txt',
  size: 2048,
  record_id: 'r1',
  record_name: 's1',
  field: 'table',
  volume: 'field-ssd',
  state: 'online',
  available: true,
  reason: '',
  fix: '',
  place: 'field-ssd',
  place_kind: 'drive',
  ...over,
})

const LISTING = {
  total: 2,
  summary: [
    {
      place: 'field-ssd',
      kind: 'drive',
      files: 1,
      bytes: 2048,
      reason: '',
      fix: '',
    },
    {
      place: 'server',
      kind: 'server',
      files: 1,
      bytes: 512,
      reason: '',
      fix: '',
    },
  ],
  items: [
    file({}),
    file({
      path: 'Encounter 7/s2/table.txt',
      sha256: 'bbb',
      record_id: 'r2',
      record_name: 's2',
      volume: null,
      state: 'remote',
      available: false,
      place: 'server',
      place_kind: 'server',
    }),
  ],
}

function show() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <MemoryRouter>
          <FilesView selection={{ collection: 'hb' }} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('FilesView', () => {
  it('says where every file is, and lists one place when it is picked', async () => {
    const calls = fakeServer({
      '/api/file-access/files': LISTING,
      '/api/schemas': [],
      '/api/remote': { configured: true, serving: false },
      '/api/store/volumes': [],
    })
    show()
    expect(await screen.findByText('All · 2 · 2.5 KB')).toBeInTheDocument()
    expect(screen.getByText('Not on this computer · 1')).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('s2')).toBeInTheDocument()

    await userEvent.click(screen.getByText('field-ssd · 1 · 2.0 KB'))
    await waitFor(() =>
      expect(
        calls.filter((c) => c.path === '/api/file-access/files').slice(-1)[0]
          ?.body,
      ).toMatchObject({ collection: 'hb', place: 'field-ssd' }),
    )
  })

  it('downloads the ticked files that are only on the server', async () => {
    const calls = fakeServer({
      '/api/file-access/files': LISTING,
      '/api/file-access/download': { fetched: 1, absent: 0 },
      '/api/schemas': [],
      '/api/remote': { configured: true, serving: false },
      '/api/store/volumes': [],
    })
    show()
    await screen.findByText('s2')
    await userEvent.click(
      screen.getByRole('checkbox', { name: 'Tick Encounter 7/s2/table.txt' }),
    )
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Download to this computer' }),
    )
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/file-access/download')?.body,
      ).toMatchObject({ collection: 'hb', shas: ['bbb'], place: 'server' }),
    )
  })

  it('ticks beyond the page: every file the filters match', async () => {
    const calls = fakeServer({
      '/api/file-access/files': { ...LISTING, total: 120 },
      '/api/file-access/download': { fetched: 60, absent: 0 },
      '/api/schemas': [],
      '/api/remote': { configured: true, serving: false },
      '/api/store/volumes': [],
    })
    show()
    await screen.findByText('s2')
    await userEvent.click(
      screen.getByRole('checkbox', { name: 'Tick every file on this page' }),
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Select all 120 matching' }),
    )
    expect(screen.getByText('All 120 matching selected')).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Download to this computer' }),
    )
    const sent = await waitFor(() => {
      const c = calls.find((x) => x.path === '/api/file-access/download')
      expect(c).toBeTruthy()
      return c!.body
    })
    // The filters as they are, not the ticked rows of one page.
    expect(sent).toMatchObject({ collection: 'hb', place: 'server' })
    expect(sent).not.toHaveProperty('shas')
  })

  it('narrows to kinds of file, several at once, counted for each kind', async () => {
    const calls = fakeServer({
      '/api/file-access/files': {
        ...LISTING,
        kinds: [
          { field: 'selection_table', files: 120, bytes: 0 },
          { field: 'contour_file', files: 64, bytes: 0 },
          { field: 'audio', files: 3, bytes: 0 },
        ],
      },
      '/api/schemas': [],
      '/api/remote': { configured: true, serving: false },
      '/api/store/volumes': [],
    })
    show()
    await userEvent.click(
      await screen.findByRole('button', { name: /Kinds of file: all/ }),
    )
    await userEvent.click(
      screen.getByRole('checkbox', { name: 'Selection Table (120)' }),
    )
    await userEvent.click(screen.getByRole('checkbox', { name: 'Audio (3)' }))
    await waitFor(() =>
      expect(
        calls.filter((c) => c.path === '/api/file-access/files').slice(-1)[0]
          ?.body,
      ).toMatchObject({ fields: ['selection_table', 'audio'] }),
    )
  })
})
