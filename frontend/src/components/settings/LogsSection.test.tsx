import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import LogsSection from './LogsSection'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })

const source = (id: string, name: string) => ({
  id,
  name,
  about: `About ${name}`,
  path: `/somewhere/${id}.log`,
  exists: true,
  size: 2048,
  modified: '2026-10-08T10:46:44Z',
})

let reads: URLSearchParams[]
let paths: string[]

beforeEach(() => {
  reads = []
  paths = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/logs')
        return json([
          source('project', 'This project’s server'),
          source('launcher', 'Desktop app launcher'),
        ])
      paths.push(url.pathname)
      reads.push(url.searchParams)
      const id = url.pathname.split('/').pop()!
      return json({
        source: source(
          id,
          id === 'launcher' ? 'Desktop app launcher' : 'This project’s server',
        ),
        lines: [
          {
            time: '2026-10-08T10:00:00Z',
            level: 'info',
            message: 'started',
            fields: {},
          },
          {
            time: '2026-10-08T10:00:02Z',
            level: 'error',
            message: 'push failed',
            fields: { request_id: 'r1' },
          },
        ],
      })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderAt(url = '/settings/logs') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <LogsSection />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LogsSection', () => {
  it('shows the first log, newest line first, with where it is', async () => {
    renderAt()
    expect(await screen.findByText('push failed')).toBeTruthy()
    const rows = screen.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('push failed')).toBeTruthy()
    expect(within(rows[0]).getByText('request_id=r1')).toBeTruthy()
    expect(screen.getByText(/\/somewhere\/project\.log/)).toBeTruthy()
    expect(paths[0]).toBe('/api/logs/project')
    expect(
      screen.getByRole('link', { name: 'Download' }).getAttribute('href'),
    ).toBe('/api/logs/project/download')
  })

  it('opens at the log and level a link names', async () => {
    renderAt('/settings/logs?log=launcher&level=warning')
    await screen.findByText('push failed')
    expect(paths[0]).toBe('/api/logs/launcher')
    expect(reads[0].get('level')).toBe('warning')
  })

  it('switches log from the picker', async () => {
    const user = userEvent.setup()
    renderAt()
    await screen.findByText('push failed')
    await user.selectOptions(screen.getByLabelText('Log'), 'launcher')
    await waitFor(() => expect(paths).toContain('/api/logs/launcher'))
  })
})
