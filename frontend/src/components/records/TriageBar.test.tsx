import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ToastProvider } from '../ui'
import { TriageBar } from './TriageBar'
import { startSession } from '../../utils/triage'
import type { CivexRecord } from '../../api/records'
import type { Field } from '../../api/schemas'

const field = (name: string, type: string): Field => ({
  id: `f-${name}`,
  name,
  label: null,
  type,
  required: false,
  restrictions: {},
  default: null,
  position: 0,
})

const record = (id: string): CivexRecord => ({
  id,
  dataset_id: 'd',
  schema_name: 'selection',
  parent_record_id: null,
  data: { note: 'x', reviewed: false },
  natural_name: id,
  created_at: '',
  updated_at: '',
  deleted_at: null,
  reference_labels: null,
})

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function renderBar(sessionId: string | null, fields: Field[]) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/records/b']}>
          <Routes>
            <Route
              path="/records/:id"
              element={
                <>
                  <TriageBar
                    sessionId={sessionId}
                    record={record('b')}
                    fields={fields}
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
}

let patched: { url: string; body: unknown } | null
beforeEach(() => {
  patched = null
  sessionStorage.clear()
  localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PATCH')
        patched = { url: String(input), body: JSON.parse(String(init.body)) }
      return json(record('b'))
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

const FIELDS = [field('note', 'string'), field('reviewed', 'boolean')]

describe('TriageBar', () => {
  it('shows nothing for a record opened without a list', () => {
    renderBar(null, FIELDS)
    expect(screen.queryByRole('region', { name: 'Triage' })).toBeNull()
  })

  it('shows nothing when the token is for a list the record is not in', () => {
    const s = startSession(sessionStorage, 'Other', ['x', 'y'])
    renderBar(s.id, FIELDS)
    expect(screen.queryByRole('region', { name: 'Triage' })).toBeNull()
  })

  it('shows where you are in the list', () => {
    const s = startSession(sessionStorage, 'Missing table', ['a', 'b', 'c'])
    renderBar(s.id, FIELDS)
    expect(screen.getByText('Missing table')).toBeInTheDocument()
    expect(screen.getByText('2 of 3')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Previous/ })).toHaveAttribute(
      'href',
      `/records/a?triage=${s.id}`,
    )
    expect(screen.getByText('0 reviewed this session')).toBeInTheDocument()
  })

  it('marks reviewed, counts it, and moves on to the next record', async () => {
    const user = userEvent.setup()
    const s = startSession(sessionStorage, 'Missing table', ['a', 'b', 'c'])
    renderBar(s.id, FIELDS)
    await user.click(
      screen.getByRole('button', { name: /Mark reviewed & next/ }),
    )
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(
        `/records/c?triage=${s.id}`,
      ),
    )
    expect(patched?.url).toContain('/records/b')
    expect(patched?.body).toEqual({ data: { note: 'x', reviewed: true } })
    expect(screen.getByText('1 reviewed this session')).toBeInTheDocument()
  })

  it('skips without writing anything', async () => {
    const user = userEvent.setup()
    const s = startSession(sessionStorage, 'Missing table', ['a', 'b', 'c'])
    renderBar(s.id, FIELDS)
    await user.click(screen.getByRole('button', { name: /Skip/ }))
    expect(screen.getByTestId('where')).toHaveTextContent(
      `/records/c?triage=${s.id}`,
    )
    expect(patched).toBeNull()
  })

  it('cannot mark a schema that has no yes/no field, but still steps through', () => {
    const s = startSession(sessionStorage, 'Missing table', ['a', 'b', 'c'])
    renderBar(s.id, [field('note', 'string')])
    expect(screen.getByRole('button', { name: /Mark reviewed/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Skip/ })).toBeEnabled()
  })
})
