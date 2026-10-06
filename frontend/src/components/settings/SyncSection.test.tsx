import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import SyncSection from './SyncSection'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

let status: Record<string, unknown>
let conflicts: Record<string, unknown>[]
let identity: Record<string, unknown>
let calls: { method: string; path: string; body: unknown }[]

const base = {
  configured: false,
  remote: null,
  project_id: 'p',
  paused: false,
  interval_seconds: 60,
  serving: false,
  pending: 0,
  open_conflicts: 0,
  last_synced_at: null,
  last_error: null,
  last_error_at: null,
  running: false,
  last_result: null,
  progress: null,
  connecting: false,
  connect_error: null,
}

beforeEach(() => {
  status = { ...base }
  conflicts = []
  identity = { name: 'sulli', chosen: null, default: 'sulli' }
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method: init?.method ?? 'GET', path: url.pathname, body })
      if (url.pathname === '/api/remote/connect') {
        status = { ...status, configured: true, remote: body.url }
        return json({ mode: 'joined' })
      }
      if (url.pathname === '/api/settings/identity') {
        if (init?.method === 'PATCH')
          identity = { ...identity, chosen: body.name }
        return json(identity)
      }
      if (url.pathname === '/api/remote/conflicts') return json(conflicts)
      if (url.pathname.endsWith('/resolve')) {
        conflicts = []
        status = { ...status, open_conflicts: 0 }
        return json(status)
      }
      if (url.pathname === '/api/remote' && init?.method === 'PATCH') {
        status = { ...status, ...body }
        return json(status)
      }
      if (url.pathname === '/api/remote') return json(status)
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SyncSection />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SyncSection', () => {
  it('connects with an address and a token', async () => {
    renderSection()
    const connect = await screen.findByRole('button', { name: 'Connect' })
    expect(connect).toBeDisabled()
    await userEvent.type(
      screen.getByLabelText('Authority address'),
      'https://civex.example.com',
    )
    await userEvent.type(screen.getByLabelText('Device token'), 'secret')
    await userEvent.click(connect)
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/api/remote/connect')?.body).toEqual(
        {
          url: 'https://civex.example.com',
          token: 'secret',
        },
      ),
    )
    expect(
      await screen.findByText('https://civex.example.com'),
    ).toBeInTheDocument()
  })

  it('shows where it stands and pauses', async () => {
    status = {
      ...base,
      configured: true,
      remote: 'https://a.example',
      pending: 3,
      last_error: 'Could not reach the authority',
    }
    renderSection()
    expect(await screen.findByText('Could not sync')).toBeInTheDocument()
    expect(
      screen.getByText(/Could not reach the authority/),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(
      await screen.findByRole('button', { name: 'Resume' }),
    ).toBeInTheDocument()
  })

  it('says how many need a look and leads to the review', async () => {
    status = {
      ...base,
      configured: true,
      remote: 'https://a.example',
      open_conflicts: 3,
    }
    renderSection()
    expect(await screen.findByText('Needs a look')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Review' })).toHaveAttribute(
      'href',
      '/sync/review',
    )
  })

  it('can be set to never sync by itself', async () => {
    status = { ...base, configured: true, remote: 'https://a.example' }
    renderSection()
    const pick = await screen.findByLabelText('How often to look for changes')
    await userEvent.selectOptions(pick, '0')
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === 'PATCH' && c.path === '/api/remote')
          ?.body,
      ).toEqual({ interval_seconds: 0 }),
    )
    expect(await screen.findByText('Up to date')).toBeInTheDocument()
  })

  it('says changes are waiting rather than up to date', async () => {
    status = {
      ...base,
      configured: true,
      remote: 'https://a.example',
      pending: 26,
    }
    renderSection()
    expect(
      await screen.findByText('26 changes waiting to send'),
    ).toBeInTheDocument()
  })

  it('lets a person choose the name recorded on their changes', async () => {
    renderSection()
    const box = await screen.findByLabelText('Author name')
    await userEvent.type(box, 'Dana')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(
        calls.find(
          (c) => c.method === 'PATCH' && c.path === '/api/settings/identity',
        )?.body,
      ).toEqual({ name: 'Dana' }),
    )
  })
})

describe('copying from the server', () => {
  it('shows how far the copy has got', async () => {
    status = {
      ...base,
      configured: true,
      remote: 'https://a',
      connecting: true,
      progress: { phase: 'copying', done: 30, total: 120, kind: 'record' },
    }
    renderSection()
    expect(
      await screen.findByText('Copying the project from the server'),
    ).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute(
      'aria-valuenow',
      '25',
    )
  })

  it('offers to try again when the copy stopped, without asking for the token', async () => {
    status = {
      ...base,
      configured: true,
      remote: 'https://a',
      connect_error: 'The connection dropped',
    }
    renderSection()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Try again' }),
    )
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/api/remote/connect')?.body).toEqual(
        {
          url: 'https://a',
        },
      ),
    )
  })
})
