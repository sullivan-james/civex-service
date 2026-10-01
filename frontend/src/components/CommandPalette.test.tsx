import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { CommandPalette } from './CommandPalette'
import { PINS_KEY, readPins } from '../utils/pins'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

const COLLECTIONS = [
  {
    id: 'c1',
    name: 'Whale song',
    description: null,
    timezone: null,
    record_count: 3,
    deleted_at: null,
    scope: 'local',
    schemas: [],
  },
]
const VIEWS = [
  {
    id: 'v1',
    schema_id: 's1',
    schema_name: 'selection',
    name: 'Missing selection_table',
    columns: [],
    filter_tree: null,
    sort: [],
  },
]
const SCHEMAS = [
  {
    id: 's1',
    name: 'selection',
    label: null,
    description: null,
    parent_id: null,
    display_fields: [],
    fields: [],
    deleted_at: null,
  },
]

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function renderPalette(onClose = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <CommandPalette onClose={onClose} />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return onClose
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://x').pathname
      if (path === '/api/collections') return json(COLLECTIONS)
      if (path === '/api/schemas') return json(SCHEMAS)
      if (path === '/api/views') return json(VIEWS)
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('CommandPalette', () => {
  it('lists pinned things when nothing is typed', async () => {
    localStorage.setItem(
      PINS_KEY,
      JSON.stringify([
        {
          key: 'collection:c1',
          kind: 'collection',
          label: 'Whale song',
          to: '/collections/c1',
        },
      ]),
    )
    renderPalette()
    expect(await screen.findByText('Pinned')).toBeInTheDocument()
    expect(screen.getByText('Whale song')).toBeInTheDocument()
  })

  it('finds a saved filter by typing, and opens it', async () => {
    const user = userEvent.setup()
    const onClose = renderPalette()
    await user.type(screen.getByRole('combobox'), 'missing table')
    await user.click(await screen.findByText('Missing selection_table'))
    expect(onClose).toHaveBeenCalled()
    expect(screen.getByTestId('where')).toHaveTextContent(
      '/schemas/s1/records?view=Missing%20selection_table',
    )
  })

  it('pins a result with its star without opening it', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'whale')
    await user.click(
      await screen.findByRole('button', { name: 'Pin Whale song' }),
    )
    expect(readPins(localStorage).map((p) => p.label)).toEqual(['Whale song'])
    expect(screen.getByTestId('where')).toHaveTextContent('/')
    expect(
      screen.getByRole('button', { name: 'Unpin Whale song' }),
    ).toBeInTheDocument()
  })

  it('opens the highlighted result with Enter', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'se')
    await screen.findByText('Missing selection_table')
    await user.keyboard('{Enter}')
    expect(screen.getByTestId('where').textContent).not.toBe('/')
  })

  it('says so when nothing matches', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'zzzz')
    expect(await screen.findByText(/Nothing matches/)).toBeInTheDocument()
  })
})
