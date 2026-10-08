import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import UpdatesSection from './UpdatesSection'

const upToDate = {
  current: '2.0.0rc1',
  latest: '2.0.0rc1',
  newer: false,
  pre: false,
  installer: 'desktop',
  can_update: true,
  blocked: '',
  error: '',
  last: null,
  running: [] as string[],
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderWith(commandLine: Record<string, unknown>) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.startsWith('/api/update')) return json(upToDate)
      if (init?.method === 'POST')
        return json({ ...commandLine, on_path: true, where: 'C:\\civex\\bin' })
      return json(commandLine)
    }),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UpdatesSection />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

const offPath = {
  available: true,
  on_path: false,
  where: null,
  shadowed_by: null,
  note: '',
}

describe('UpdatesSection: command line', () => {
  it('offers to add the desktop app’s civex to PATH', async () => {
    const calls = renderWith(offPath)
    const add = await screen.findByRole('button', { name: 'Add to PATH' })
    await userEvent.click(add)
    await screen.findByRole('button', { name: 'Remove from PATH' })
    expect(calls).toContain('POST /api/settings/command-line')
  })

  it('is not shown for a civex that already is a command', async () => {
    renderWith({ ...offPath, available: false })
    await waitFor(() =>
      expect(screen.getByText(/is up to date/)).toBeInTheDocument(),
    )
    expect(screen.queryByText('Command line')).not.toBeInTheDocument()
  })
})

function renderStatus(status: Record<string, unknown>) {
  const calls: { method: string; url: string; body?: unknown }[] = []
  let current = status
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (method === 'DELETE') {
        current = { ...current, last: null }
        return new Response(null, { status: 204 })
      }
      if (url.startsWith('/api/update') && method === 'POST')
        return json({ restarting: true })
      if (url.startsWith('/api/update')) return json(current)
      return json({ available: false })
    }),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UpdatesSection />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return calls
}

describe('UpdatesSection: updating', () => {
  it('says what else runs from this copy, and stops it to update', async () => {
    const calls = renderStatus({
      ...upToDate,
      latest: '2.0.0rc6',
      newer: true,
      running: ['civex serve --port 8100 --allow-remote (in C:\\ocean)'],
    })
    expect(
      await screen.findByText(
        'civex serve --port 8100 --allow-remote (in C:\\ocean)',
      ),
    ).toBeTruthy()
    await userEvent.click(
      screen.getByRole('button', {
        name: 'Stop it, update to 2.0.0rc6 and restart',
      }),
    )
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
        pre: false,
        version: '2.0.0rc6',
        stop_others: true,
      }),
    )
  })

  it('dismisses the last update’s outcome on the server', async () => {
    const calls = renderStatus({
      ...upToDate,
      last: {
        at: '2026-10-08T10:46:44Z',
        from_version: '2.0.0rc4',
        to_version: '2.0.0rc4',
        ok: false,
        message: 'Not updated.',
      },
    })
    await userEvent.click(
      await screen.findByRole('button', { name: 'Dismiss' }),
    )
    await waitFor(() =>
      expect(screen.queryByText(/didn’t install a new version/)).toBeNull(),
    )
    expect(
      calls.some((c) => c.method === 'DELETE' && c.url === '/api/update/last'),
    ).toBe(true)
  })
})
