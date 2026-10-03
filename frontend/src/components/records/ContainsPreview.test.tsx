import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ToastProvider } from '../ui'
import { ContainsPreview } from './ContainsPreview'

const field = (name: string) => ({
  id: `f-${name}`,
  name,
  label: null,
  type: 'string',
  required: false,
  restrictions: {},
  default: null,
  position: 0,
})
const schema = (name: string, parent: string | null, f: string) => ({
  id: `id-${name}`,
  name,
  label: null,
  description: null,
  parent_id: parent ? `id-${parent}` : null,
  display_template: null,
  deleted_at: null,
  fields: [field(f)],
})
const SCHEMAS = [
  schema('encounter', null, 'site'),
  schema('recording', 'encounter', 'rate'),
  schema('selection', 'recording', 'table'),
]
const rec = (
  id: string,
  schema_name: string,
  data: object,
  child_counts = {},
) => ({
  id,
  dataset_id: 'd',
  schema_name,
  parent_record_id: null,
  data,
  natural_name: id.toUpperCase(),
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  deleted_at: null,
  reference_labels: null,
  child_counts,
})
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

let listCalls: URLSearchParams[]
beforeEach(() => {
  listCalls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/schemas') return json(SCHEMAS)
      if (url.pathname.endsWith('/record-counts'))
        return json({ recording: 5, selection: 9 })
      if (url.pathname.endsWith('/records')) {
        listCalls.push(url.searchParams)
        const s = url.searchParams.get('schema')
        const items =
          s === 'recording'
            ? [
                rec('r1', 'recording', { rate: '96' }, { selection: 2 }),
                rec('r2', 'recording', { rate: '48' }),
                rec('r3', 'recording', { rate: '44' }),
              ]
            : [rec('s1', 'selection', { table: 'a.txt' })]
        return json({
          items,
          total: s === 'recording' ? 5 : 9,
          offset: 0,
          limit: 3,
        })
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const l = useLocation()
  return <output data-testid="where">{l.pathname + l.search}</output>
}

describe('ContainsPreview', () => {
  it('peeks at each schema below the record and links to the full lists', async () => {
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <MemoryRouter initialEntries={['/records/e1']}>
            <Routes>
              <Route
                path="*"
                element={
                  <>
                    <ContainsPreview
                      record={{ id: 'e1', schema_name: 'encounter' }}
                      collection="hb"
                      collectionId="hb"
                    />
                    <Where />
                  </>
                }
              />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )

    const recordings = (
      await screen.findByRole('heading', { name: /Recording/ })
    ).parentElement!
    expect(recordings).toHaveTextContent('5')
    expect(
      await within(recordings.parentElement!).findByText('R1'),
    ).toBeInTheDocument()
    // a short peek of the same records the collection page lists
    expect(
      listCalls.find((p) => p.get('schema') === 'recording')!.get('limit'),
    ).toBe('3')
    expect(
      listCalls.find((p) => p.get('schema') === 'recording')!.get('within'),
    ).toBe('e1')
    expect(screen.getByText('Show 2 more in the full list')).toBeInTheDocument()

    // only a direct child of the record can be added under it
    const adds = screen.getAllByRole('link', { name: /Add/ })
    expect(adds).toHaveLength(1)
    expect(adds[0]).toHaveAttribute(
      'href',
      '/collections/hb/new?schema=recording&parent=e1',
    )

    await user.click(screen.getAllByRole('link', { name: 'View all' })[1])
    expect(screen.getByTestId('where')).toHaveTextContent(
      '/collections/hb?schema=selection&within=e1',
    )
  })
})
