import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ToastProvider } from '../ui'
import { ReferencedBy, referrersHref } from './ReferencedBy'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

const GROUPS = [
  {
    dataset_id: 'd-study',
    collection: 'study',
    schema_name: 'visit',
    field_name: 'patient_ref',
    dtype: 'reference',
    count: 2,
  },
  {
    dataset_id: 'd-study',
    collection: 'study',
    schema_name: 'cohort',
    field_name: 'members',
    dtype: 'reference_list',
    count: 1,
  },
]

let referrerCalls: string[]
beforeEach(() => {
  referrerCalls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/records/p1/referrers') {
        referrerCalls.push(url.pathname)
        return json(GROUPS)
      }
      if (url.pathname === '/api/records/none/referrers') return json([])
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const l = useLocation()
  return <output data-testid="where">{l.pathname + l.search}</output>
}

function renderIt(recordId: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/records/' + recordId]}>
          <Routes>
            <Route
              path="*"
              element={
                <>
                  <ReferencedBy recordId={recordId} />
                  <Where />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('ReferencedBy', () => {
  it('lists the groups', async () => {
    renderIt('p1')
    expect(await screen.findByText(/via Patient Ref/)).toBeInTheDocument()
    expect(screen.getByText(/via Members/)).toBeInTheDocument()
    expect(referrerCalls).toHaveLength(1)
  })

  it('links a group to its collection, filtered to this record', async () => {
    const user = userEvent.setup()
    renderIt('p1')
    await screen.findByText(/via Patient Ref/)

    await user.click(
      (await screen.findAllByRole('link', { name: 'View all' }))[0],
    )

    const where = screen.getByTestId('where').textContent!
    const url = new URL(where, 'http://x')
    expect(url.pathname).toBe('/collections/d-study')
    expect(url.searchParams.get('schema')).toBe('visit')
    expect(JSON.parse(url.searchParams.get('filter')!)).toEqual({
      field: 'patient_ref',
      op: 'eq',
      value: 'p1',
    })
  })

  it('says so when nothing references the record', async () => {
    const user = userEvent.setup()
    renderIt('none')
    expect(
      await screen.findByText('Nothing references this record.'),
    ).toBeInTheDocument()
  })
})

describe('referrersHref', () => {
  it('matches a single reference exactly and a list by membership', () => {
    const base = {
      dataset_id: 'd',
      collection: 'c',
      schema_name: 's',
      field_name: 'f',
      count: 1,
    }
    const op = (dtype: 'reference' | 'reference_list') =>
      JSON.parse(
        new URL(
          referrersHref({ ...base, dtype }, 'rid'),
          'http://x',
        ).searchParams.get('filter')!,
      ).op
    expect(op('reference')).toBe('eq')
    expect(op('reference_list')).toBe('contains')
  })
})
