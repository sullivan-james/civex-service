import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import ConnectPage from './ConnectPage'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const idle = {
  configured: false,
  remote: null,
  project_id: 'p',
  connecting: false,
  connect_error: null,
  progress: null,
  awaiting_approval: null,
}

let status: Record<string, unknown>
let collections: unknown[]
let joined: boolean | null
let answer: Record<string, unknown>
let calls: { path: string; body: unknown }[]
const open = vi.fn()

beforeEach(() => {
  status = { ...idle }
  collections = []
  answer = { mode: 'joined' }
  joined = true
  calls = []
  open.mockReset()
  vi.stubGlobal('open', open)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      if (init?.method === 'POST') calls.push({ path: url.pathname, body })
      if (url.pathname === '/api/remote/connect') {
        if (answer.mode === 'approval')
          status = {
            ...idle,
            connecting: true,
            awaiting_approval: {
              code: answer.code,
              expires_at: 2_000_000_000,
              verify_url: answer.verify_url,
            },
          }
        else status = { ...idle, connecting: true }
        return json(answer, 202)
      }
      if (url.pathname === '/api/remote/known') return json({ joined })
      if (url.pathname === '/api/remote') return json(status)
      if (url.pathname === '/api/collections') return json(collections)
      return json([])
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderPage(search = '?url=https://hub.example/ada/notes') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/connect${search}`]}>
        <Routes>
          <Route path="/connect" element={<ConnectPage />} />
          <Route path="/" element={<p>Home reached</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ConnectPage', () => {
  it('says an empty project becomes a copy, and sends the sync address', async () => {
    renderPage()
    expect(await screen.findByTestId('plan')).toHaveTextContent(
      'This project is empty. It will become a copy of ada/notes on hub.example.',
    )
    expect(
      screen.getByRole('button', { name: 'Connect to hub.example' }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Invite code')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^Connect/ }))
    await waitFor(() =>
      expect(calls[0]).toEqual({
        path: '/api/remote/connect',
        body: { url: 'https://hub.example/ada/notes/data' },
      }),
    )
  })

  it('says what happens to a project that has data', async () => {
    collections = [{ id: 'c1', name: 'Humpbacks', record_count: 3 }]
    renderPage()
    expect(await screen.findByTestId('plan')).toHaveTextContent(
      /has data.*only connect to a project with nothing in it/,
    )
    // Sending data away needs a yes that names the host.
    const button = screen.getByRole('button', { name: /^Connect/ })
    expect(button).toBeDisabled()
    await userEvent.click(
      screen.getByRole('checkbox', {
        name: "Send this project's data to hub.example",
      }),
    )
    expect(button).toBeEnabled()
    await userEvent.click(button)
    await waitFor(() => expect(calls).toHaveLength(1))
  })

  it('warns, more strongly for data, about a hub never used before', async () => {
    joined = false
    collections = [{ id: 'c1', name: 'Humpbacks', record_count: 3 }]
    renderPage('?url=https://hub.civex.uk.evil.com/ada/notes')
    expect(await screen.findByText(/has not connected to/)).toHaveTextContent(
      'hub.civex.uk.evil.com',
    )
    expect(
      screen.getByRole('checkbox', {
        name: /hub.civex.uk.evil.com, a hub I have not used before/,
      }),
    ).toBeInTheDocument()
  })

  it('says nothing about a hub it could not check', async () => {
    joined = null
    renderPage('?url=https://hub.example/ada/notes')
    expect(await screen.findByTestId('plan')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 800))
    expect(screen.queryByText(/has not connected to/)).toBeNull()
  })

  it('refuses an address with a user name in it', async () => {
    renderPage('?url=https://hub.example@evil.example/ada/notes')
    expect(await screen.findByRole('alert')).toHaveTextContent('no user name')
    expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled()
  })

  it.each([
    'javascript:alert(1)',
    'data:text/html,hi',
    'https://evil.example/ada/notes/device',
    '/ada/notes/device',
  ])('never opens or links a hostile approval page (%s)', async (bad) => {
    answer = {
      mode: 'approval',
      code: 'ABCD-2345',
      expires_at: 2_000_000_000,
      verify_url: bad,
    }
    renderPage()
    await userEvent.click(
      await screen.findByRole('button', { name: /^Connect/ }),
    )
    expect(await screen.findByText('ABCD-2345')).toBeInTheDocument()
    expect(open).not.toHaveBeenCalled()
    expect(
      screen.queryByRole('link', { name: 'Approve in your browser' }),
    ).not.toBeInTheDocument()
  })

  it('opens the approval page with the code, then carries on to Home', async () => {
    answer = {
      mode: 'approval',
      code: 'ABCD-2345',
      expires_at: 2_000_000_000,
      verify_url: 'https://hub.example/ada/notes/device',
    }
    renderPage()
    await userEvent.click(
      await screen.findByRole('button', { name: /^Connect/ }),
    )
    expect(
      await screen.findByRole('link', { name: 'Approve in your browser' }),
    ).toHaveAttribute(
      'href',
      'https://hub.example/ada/notes/device?code=ABCD-2345',
    )
    expect(screen.getByText('ABCD-2345')).toBeInTheDocument()
    expect(open).toHaveBeenCalledWith(
      'https://hub.example/ada/notes/device?code=ABCD-2345',
      '_blank',
      'noopener',
    )
    // Approved: the connect finishes by itself.
    status = { ...idle, configured: true, remote: 'https://hub.example' }
    expect(
      await screen.findByText('Home reached', {}, { timeout: 4000 }),
    ).toBeInTheDocument()
  })

  it('shows copying progress and waits for it', async () => {
    renderPage()
    await userEvent.click(
      await screen.findByRole('button', { name: /^Connect/ }),
    )
    status = {
      ...idle,
      configured: true,
      connecting: true,
      progress: { phase: 'copying', kind: 'record', done: 5, total: 10 },
    }
    expect(
      await screen.findByText(/Copying the project/, {}, { timeout: 4000 }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Home reached')).not.toBeInTheDocument()
  })

  it('names who to ask when the hub says no', async () => {
    renderPage()
    await userEvent.click(
      await screen.findByRole('button', { name: /^Connect/ }),
    )
    status = {
      ...idle,
      connect_error: 'The server refused this device: not allowed',
      connect_error_kind: 'no_access',
    }
    expect(
      await screen.findByText(/refused this device/, {}, { timeout: 4000 }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ada/notes' })).toHaveAttribute(
      'href',
      'https://hub.example/ada/notes',
    )
    expect(screen.getByText(/to let you in/)).toBeInTheDocument()
  })

  it('does not blame access for a network error', async () => {
    renderPage()
    await userEvent.click(
      await screen.findByRole('button', { name: /^Connect/ }),
    )
    status = {
      ...idle,
      connect_error: 'Could not reach the server, check access and try again',
    }
    expect(
      await screen.findByText(/Could not reach/, {}, { timeout: 4000 }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/to let you in/)).not.toBeInTheDocument()
  })

  it('refuses an address that is not a web address', async () => {
    renderPage('?url=ssh://me@box/p')
    expect(await screen.findByRole('alert')).toHaveTextContent('web address')
    expect(screen.getByRole('button', { name: /^Connect/ })).toBeDisabled()
  })
})
