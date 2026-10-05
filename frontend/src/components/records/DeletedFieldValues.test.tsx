import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { DeletedFieldValues } from './DeletedFieldValues'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const FIELD = 'f1f1f1f1-0000-4000-8000-000000000001'

const plan = (over: Record<string, unknown> = {}) => ({
  kind: 'field',
  id: FIELD,
  name: 'note',
  records: 0,
  blocked_by: null,
  blocked: null,
  collection: null,
  collection_id: null,
  schema_name: 'thing',
  deleted_at: '2026-03-04T10:00:00Z',
  can_restore: true,
  ...over,
})

let calls: { method: string; path: string }[]
let planBody: Record<string, unknown>

beforeEach(() => {
  calls = []
  planBody = plan()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      calls.push({ method: init?.method ?? 'GET', path: url.pathname })
      if (url.pathname.endsWith('/restore-plan')) return json(planBody)
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <DeletedFieldValues
            fields={[
              {
                id: FIELD,
                name: 'note',
                label: 'Note',
                dtype: 'string',
                schema_name: 'thing',
                deleted_at: '2026-03-04T10:00:00Z',
                value: 'keep me',
              },
            ]}
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('DeletedFieldValues', () => {
  it('shows the value, that the field was deleted, and that it can come back', () => {
    renderIt()
    expect(screen.getByText('Note')).toBeInTheDocument()
    expect(screen.getByText('keep me')).toBeInTheDocument()
    expect(screen.getByText(/Deleted .*It can be restored/)).toBeInTheDocument()
  })

  it('shows nothing when no field was deleted', () => {
    const qc = new QueryClient()
    const { container } = render(
      <QueryClientProvider client={qc}>
        <DeletedFieldValues fields={[]} />
      </QueryClientProvider>,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('says what coming back does, then restores the field on its schema', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('button', { name: 'Restore…' }))

    expect(
      await screen.findByText(/comes back on the schema .*thing/),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Restore' }))

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: `/api/schemas/thing/fields/${FIELD}/restore`,
      }),
    )
    expect(calls).toContainEqual({
      method: 'GET',
      path: `/api/schemas/thing/fields/${FIELD}/restore-plan`,
    })
  })

  it('will not restore a field whose name has been taken, and says why', async () => {
    planBody = plan({
      can_restore: false,
      blocked:
        "A field named 'note' now exists on 'thing'. Rename or delete it, then restore this one.",
    })
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('button', { name: 'Restore…' }))

    expect(await screen.findByText(/now exists on 'thing'/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restore' })).toBeDisabled()
  })

  it('offers to restore the schema first when the schema is deleted', async () => {
    planBody = plan({
      can_restore: false,
      blocked_by: { kind: 'schema', id: 's1', name: 'thing' },
      blocked:
        "'note' is a field of the schema 'thing', which is deleted. Restore that first.",
    })
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('button', { name: 'Restore…' }))

    expect(
      await screen.findByRole('button', {
        name: /Restore the schema .*thing.* and all of it/,
      }),
    ).toBeInTheDocument()
  })
})
