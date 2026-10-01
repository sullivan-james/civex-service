import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { PinnedNav } from './PinnedNav'
import { PINS_KEY, readPins } from '../utils/pins'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://x').pathname
      if (path.endsWith('/views/Missing%20table'))
        return json({
          id: 'v',
          schema_id: 's',
          schema_name: 'selection',
          name: 'Missing table',
          columns: [],
          filter_tree: null,
          sort: [],
        })
      if (path === '/api/schemas/selection/records')
        return json({ items: [], total: 14, offset: 0, limit: 1 })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderNav() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <PinnedNav collapsed={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PinnedNav', () => {
  it('renders nothing when nothing is pinned', () => {
    renderNav()
    expect(screen.queryByText('Pinned')).toBeNull()
  })

  it('shows a pinned filter with its live count, and unpins it', async () => {
    localStorage.setItem(
      PINS_KEY,
      JSON.stringify([
        {
          key: 'view:selection/Missing table',
          kind: 'view',
          label: 'Missing table',
          to: '/schemas/s/records?view=Missing%20table',
          schema: 'selection',
          view: 'Missing table',
        },
      ]),
    )
    renderNav()
    expect(await screen.findByLabelText('14 matching')).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Unpin Missing table' }),
    )
    expect(readPins(localStorage)).toEqual([])
    expect(screen.queryByText('Missing table')).toBeNull()
  })
})
