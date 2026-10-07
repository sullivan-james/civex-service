import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
      <UpdatesSection />
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
