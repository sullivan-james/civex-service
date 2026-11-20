import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui'
import AnalyticsPage from './AnalyticsPage'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })

const BY_SITE = {
  id: '11111111-1111-1111-1111-111111111111',
  schema_id: 'id-sample',
  schema_name: 'sample',
  name: 'By site',
  columns: [],
  filter_tree: null,
  sort: [],
  files_layout: 'tree',
  summary: {
    group_by: ['site'],
    measures: ['count'],
    sort: null,
    show: 'table',
    chart_measure: null,
    collection: 'c1',
    within: null,
    search: null,
  },
}

const SUMMARY = {
  schema_name: 'sample',
  group_columns: [
    {
      key: 'site',
      field: 'site',
      schema_name: 'sample',
      label: 'Site',
      type: 'string',
      unit: null,
    },
  ],
  measure_columns: [
    {
      key: 'count',
      measure: 'count',
      label: 'Records',
      field: null,
      schema_name: null,
      type: null,
      unit: null,
    },
  ],
  rows: [
    {
      groups: [
        {
          value: 'North',
          label: 'North',
          lower: null,
          upper: null,
          precision: null,
        },
      ],
      values: [4],
      where: null,
    },
  ],
  total: [4],
  truncated: false,
  limit: 1000,
  timezone: null,
}

let cards: unknown[]
let me: unknown
let puts: { cards: unknown[] }[]

beforeEach(() => {
  cards = []
  puts = []
  me = undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      if (url.pathname === '/api/dashboard') {
        if (method === 'PUT') {
          const body = JSON.parse(String(init!.body))
          puts.push(body)
          cards = body.cards
        }
        return json({
          cards: (cards as { view?: string }[]).map((c) => ({
            ...c,
            analysis: c.view === BY_SITE.id ? BY_SITE : undefined,
          })),
          edited: true,
          widgets: { storage: 'Storage' },
        })
      }
      if (url.pathname === '/api/views') return json([BY_SITE])
      if (url.pathname === '/api/schemas/sample/views/By%20site/summary')
        return json(SUMMARY)
      if (url.pathname === '/api/me')
        return me ? json(me) : new Response(null, { status: 404 })
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderPage(url = '/analytics') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route path="/analytics" element={<AnalyticsPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('the Analytics page', () => {
  it('says how to make an analysis when the page is empty', async () => {
    renderPage()
    expect(
      await screen.findByText('Nothing on this page yet'),
    ).toBeInTheDocument()
    expect(screen.getByText(/choose Summary/)).toBeInTheDocument()
  })

  it('draws a saved analysis, with a way to open it in the explorer', async () => {
    cards = [{ id: 'a', kind: 'analysis', size: 'wide', view: BY_SITE.id }]
    renderPage()
    expect(await screen.findByText('North')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /Open in explorer/ }),
    ).toHaveAttribute('href', '/collections/c1?schema=sample&view=By+site')
  })

  it('adds a card while editing and saves the page once, on Done', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(
      (await screen.findAllByRole('button', { name: 'Edit page' }))[0],
    )
    await user.click(screen.getByRole('button', { name: /Add a card/ }))
    await user.click(await screen.findByRole('menuitem', { name: /By site/ }))
    const list = screen.getByRole('list', { name: 'Cards on the page' })
    expect(within(list).getByText('By site')).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: 'Full width' }))
    expect(puts).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].cards).toEqual([
      expect.objectContaining({
        kind: 'analysis',
        size: 'wide',
        view: BY_SITE.id,
      }),
    ])
    expect(await screen.findByText('North')).toBeInTheDocument()
  })

  it('lets someone who may only read see the page but not edit it', async () => {
    me = {
      account: { name: 'reader', kind: 'user', manage_url: null },
      permissions: { actions: { read: ['project'] }, all: {} },
    }
    cards = [{ id: 'a', kind: 'analysis', size: 'small', view: BY_SITE.id }]
    renderPage()
    expect(await screen.findByText('North')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Edit page' })).toBeDisabled(),
    )
  })
})
