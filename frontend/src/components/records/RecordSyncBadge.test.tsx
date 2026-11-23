import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import RecordSyncBadge from './RecordSyncBadge'

afterEach(() => vi.unstubAllGlobals())

function show(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <RecordSyncBadge recordId="r1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const base = {
  remote: 'https://hub.example',
  pending: 0,
  seeding: 0,
  hub_seq: null,
  synced_at: null,
  message: null,
  conflict_id: null,
  files: 0,
  files_waiting: 0,
}

describe('RecordSyncBadge', () => {
  it('shows a refusal with a link to review it', async () => {
    show({ ...base, state: 'refused', message: 'must be one of Y, N' })
    expect(await screen.findByText(/Refused: must be one of Y, N/)).toBeTruthy()
    expect(
      screen.getByRole('link', { name: 'Review' }).getAttribute('href'),
    ).toBe('/sync/review')
  })
  it('shows nothing when there is no authority', async () => {
    show({ ...base, state: 'not_connected' })
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByTestId('record-sync')).toBeNull()
  })
})
