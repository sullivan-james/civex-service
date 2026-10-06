import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { ExportsList } from './ExportsList'
import { fakeServer, json } from './testSupport'

afterEach(() => vi.unstubAllGlobals())

const info = (over: Record<string, unknown> = {}) => ({
  name: 'hb-selection',
  location: 'project',
  path: '/proj/_civex/exports/hb-selection',
  files: 4,
  bytes_on_disk: 0,
  linked: 4,
  copied: 0,
  updated: '2026-10-05T19:20:00Z',
  ...over,
})

const copies = info({
  name: 'hb-copies',
  location: 'archive',
  path: '/mnt/archive/_exports/hb-copies',
  files: 2,
  bytes_on_disk: 3 * 1024 ** 3,
  linked: 0,
  copied: 2,
})

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <ExportsList />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const routes = (over: Record<string, unknown> = {}) => ({
  '/api/file-access/exports': [],
  ...over,
})

describe('The exports made', () => {
  it('lists each export with where it is and what it costs', async () => {
    fakeServer(routes({ '/api/file-access/exports': [info(), copies] }))
    renderIt()

    expect(await screen.findByText('hb-selection')).toBeTruthy()
    expect(screen.getByText(/on the project folder/i)).toBeTruthy()
    expect(screen.getByText(/4 files · 4 linked · no space used/)).toBeTruthy()
    expect(screen.getByText(/on archive/)).toBeTruthy()
    expect(
      screen.getByText(/2 files · 2 copied · 3\.0 GB on disk/),
    ).toBeTruthy()
    expect(screen.getByText(/copies are using 3\.0 GB/i)).toBeTruthy()
  })

  it('says how little it knows about an export made before sizes were recorded', async () => {
    fakeServer(
      routes({
        '/api/file-access/exports': [
          info({ bytes_on_disk: null, linked: null, copied: null }),
        ],
      }),
    )
    renderIt()

    expect(await screen.findByText(/^4 files · updated/)).toBeTruthy()
  })

  it('has an empty state', async () => {
    fakeServer(routes())
    renderIt()

    expect(await screen.findByText(/no exports/i)).toBeTruthy()
  })

  it('asks once before removing, then removes just that one', async () => {
    const calls = fakeServer(
      routes({
        '/api/file-access/exports': [info(), copies],
        '/api/file-access/exports/remove': {
          results: [
            {
              path: copies.path,
              removed_files: 2,
              freed_bytes: 3 * 1024 ** 3,
              kept_files: 0,
              folder_removed: true,
            },
          ],
          errors: [],
        },
      }),
    )
    renderIt()
    const row = (await screen.findByText('hb-copies')).closest('li')!

    await userEvent.click(within(row).getByRole('button', { name: /remove/i }))
    expect(calls.some((c) => c.path.endsWith('/remove'))).toBe(false)
    const confirm = screen.getByRole('dialog', { name: /remove “hb-copies”/i })
    expect(
      within(confirm).getByText(/stored files are not touched/i),
    ).toBeTruthy()
    await userEvent.click(
      within(confirm).getByRole('button', { name: /^remove$/i }),
    )

    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/remove'))?.body).toEqual({
        paths: [copies.path],
      }),
    )
    expect(
      await screen.findByText(/removed 1 export, freeing 3\.0 GB/i),
    ).toBeTruthy()
  })

  it('can remove every export at once', async () => {
    const calls = fakeServer(
      routes({
        '/api/file-access/exports': [info(), copies],
        '/api/file-access/exports/remove': { results: [], errors: [] },
      }),
    )
    renderIt()
    await screen.findByText('hb-selection')

    await userEvent.click(screen.getByRole('button', { name: /remove all 2/i }))
    const confirm = screen.getByRole('dialog', { name: /remove 2 exports/i })
    await userEvent.click(
      within(confirm).getByRole('button', { name: /^remove$/i }),
    )

    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/remove'))?.body).toEqual({
        paths: [info().path, copies.path],
      }),
    )
  })

  it('says when the user’s own files were left in place', async () => {
    fakeServer(
      routes({
        '/api/file-access/exports': [info()],
        '/api/file-access/exports/remove': {
          results: [
            {
              path: info().path,
              removed_files: 4,
              freed_bytes: 0,
              kept_files: 2,
              folder_removed: false,
            },
          ],
          errors: [],
        },
      }),
    )
    renderIt()
    await userEvent.click(
      await screen.findByRole('button', { name: /^remove$/i }),
    )
    const confirm = screen.getByRole('dialog', {
      name: /remove “hb-selection”/i,
    })
    await userEvent.click(
      within(confirm).getByRole('button', { name: /^remove$/i }),
    )

    expect(
      await screen.findByText(/2 of your own files were left in place/i),
    ).toBeTruthy()
  })

  it('reports an export that could not be removed', async () => {
    fakeServer(
      routes({
        '/api/file-access/exports': [info()],
        '/api/file-access/exports/remove': () =>
          json({
            results: [],
            errors: [
              { path: info().path, error: 'not a folder a civex export made' },
            ],
          }),
      }),
    )
    renderIt()
    await userEvent.click(
      await screen.findByRole('button', { name: /^remove$/i }),
    )
    const confirm = screen.getByRole('dialog', {
      name: /remove “hb-selection”/i,
    })
    await userEvent.click(
      within(confirm).getByRole('button', { name: /^remove$/i }),
    )

    expect(
      await screen.findByText(/not a folder a civex export made/i),
    ).toBeTruthy()
  })
})
