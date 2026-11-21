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

const SAMPLE = {
  id: 'id-sample',
  name: 'sample',
  label: null,
  description: null,
  parent_id: null,
  display_template: null,
  deleted_at: null,
  charts: [],
  fields: [
    {
      id: 'f1',
      name: 'site',
      label: null,
      type: 'string',
      required: false,
      restrictions: {},
      default: null,
      position: 0,
    },
  ],
}

/** A chart card as the server serves it: per site, of the deep samples in
 * one collection. */
const PER_SITE = {
  id: 'a',
  kind: 'chart',
  size: 'wide',
  chart: { group_by: ['site'], measures: ['count'] },
  records: {
    schema: 'id-sample',
    collection: 'c1',
    filter: { field: 'depth', op: 'gt', value: 5 },
  },
  schema_name: 'sample',
  schema_label: 'Sample',
  collection_name: 'survey',
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
      where: { field: 'site', schema: 'sample', op: 'eq', value: 'North' },
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
let asked: Record<string, unknown>[]

beforeEach(() => {
  cards = []
  puts = []
  asked = []
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
        return json({ cards, edited: true, widgets: { storage: 'Storage' } })
      }
      if (url.pathname === '/api/schemas') return json([SAMPLE])
      if (url.pathname === '/api/collections')
        return json([
          { id: 'c1', name: 'survey' },
          { id: 'c2', name: 'other' },
        ])
      if (url.pathname === '/api/records/summary') {
        asked.push(JSON.parse(String(init!.body)))
        return json(SUMMARY)
      }
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
  it('says so in a few words when the page is empty', async () => {
    renderPage()
    expect(await screen.findByText('Nothing here yet')).toBeInTheDocument()
  })

  it('draws a chart over the records it was made for, with a way to them', async () => {
    cards = [PER_SITE]
    renderPage()
    expect(
      await screen.findByText('How many samples per site'),
    ).toBeInTheDocument()
    expect(await screen.findByText('North')).toBeInTheDocument()
    expect(asked[0]).toMatchObject({
      collection: 'survey',
      schema_name: 'sample',
      filter: { field: 'depth', op: 'gt', value: 5 },
      group_by: ['site'],
      measures: ['count'],
    })
    expect(screen.getByRole('link', { name: 'Records' })).toHaveAttribute(
      'href',
      expect.stringContaining('/collections/survey?schema=sample'),
    )
  })

  it('narrows every chart to the collection picked in For', async () => {
    const user = userEvent.setup()
    cards = [PER_SITE]
    renderPage()
    await screen.findByText('North')
    await user.selectOptions(screen.getByLabelText('For'), 'other')
    await waitFor(() =>
      expect(asked[asked.length - 1]).toMatchObject({ collection: 'other' }),
    )
  })

  it('enlarges a chart, with its numbers, and closes it', async () => {
    const user = userEvent.setup()
    cards = [PER_SITE]
    renderPage()
    await screen.findByText('North')
    await user.click(screen.getByRole('button', { name: /^Enlarge/ }))
    expect(
      await screen.findByRole('button', { name: /Download numbers/ }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: /Download numbers/ }),
      ).not.toBeInTheDocument(),
    )
  })

  it('keeps a chart whose kind is gone, saying so', async () => {
    cards = [
      {
        ...PER_SITE,
        schema_name: null,
        problem: 'That kind of record is gone',
      },
    ]
    renderPage()
    expect(
      await screen.findByText('That kind of record is gone'),
    ).toBeInTheDocument()
  })

  it('edits the page and saves it once, on Done, keeping each chart whole', async () => {
    const user = userEvent.setup()
    cards = [PER_SITE]
    renderPage()
    await user.click(
      (await screen.findAllByRole('button', { name: 'Edit page' }))[0],
    )
    await user.click(screen.getByRole('button', { name: /Add a card/ }))
    await user.click(await screen.findByRole('menuitem', { name: 'Storage' }))
    const list = screen.getByRole('list', { name: 'Cards on the page' })
    expect(within(list).getByText('Storage')).toBeInTheDocument()
    expect(puts).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].cards).toEqual([
      {
        id: 'a',
        kind: 'chart',
        size: 'wide',
        chart: { id: 'a', group_by: ['site'], measures: ['count'] },
        records: PER_SITE.records,
      },
      expect.objectContaining({ kind: 'widget', widget: 'storage' }),
    ])
  })

  it('lets someone who may only read see the page but not edit it', async () => {
    me = {
      account: { name: 'reader', kind: 'user', manage_url: null },
      permissions: { actions: { read: ['project'] }, all: {} },
    }
    cards = [PER_SITE]
    renderPage()
    expect(await screen.findByText('North')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Edit page' })).toBeDisabled(),
    )
  })
})
