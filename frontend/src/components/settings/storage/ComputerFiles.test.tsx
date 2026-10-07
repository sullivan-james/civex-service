import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ComputerFilesCell, ComputerFilesDefault } from './ComputerFiles'

let calls: { method: string; path: string; body: unknown }[]
let status: Record<string, unknown>
const files = [
  {
    id: 'c1',
    name: 'Humpbacks',
    mode: 'keep',
    chosen: false,
    files_here: 3,
    bytes_here: 3 * 1024 * 1024,
    files_on_server: 2,
  },
]

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

beforeEach(() => {
  calls = []
  status = {
    configured: true,
    serving: false,
    download_files: 'all',
    files_to_fetch: 7,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method: init?.method ?? 'GET', path: url.pathname, body })
      if (url.pathname === '/api/remote') return json(status)
      if (url.pathname === '/api/remote/files') return json(files)
      if (url.pathname === '/api/remote/files/c1/free-up')
        return json({
          files: 3,
          bytes: 3 * 1024 * 1024,
          kept_shared: 1,
          not_on_server: 0,
          done: url.searchParams.get('dry_run') === 'false',
        })
      if (url.pathname === '/api/remote/files/c1') return json(files)
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function show(ui: React.ReactNode) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('files on this computer', () => {
  it('says how many kept files are not here yet, and sets the default', async () => {
    show(<ComputerFilesDefault />)
    expect(
      await screen.findByText(
        /7 files this computer keeps aren't downloaded yet/,
      ),
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('radio', { name: 'Only files I open' }),
    )
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === 'PATCH' && c.path === '/api/remote')
          ?.body,
      ).toEqual({ download_files: 'opened' }),
    )
  })

  it('sets one collection to fetch its files when opened', async () => {
    show(<ComputerFilesCell collectionId="c1" />)
    await userEvent.selectOptions(
      await screen.findByLabelText(
        "Which of Humpbacks's files this computer keeps",
      ),
      'opened',
    )
    await waitFor(() =>
      expect(
        calls.find(
          (c) => c.method === 'PATCH' && c.path === '/api/remote/files/c1',
        )?.body,
      ).toEqual({ mode: 'opened' }),
    )
  })

  it('frees space after saying what goes and what stays', async () => {
    show(<ComputerFilesCell collectionId="c1" />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Free up space…' }),
    )
    expect(
      await screen.findByText(/Removes this computer.s copies of 3 files/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Keeps 1 in a collection kept on this computer/),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove 3.0 MB' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path === '/api/remote/files/c1/free-up' && c.method === 'POST',
        ),
      ).toBe(true),
    )
  })
})
