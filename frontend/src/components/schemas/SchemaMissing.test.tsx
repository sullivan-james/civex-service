import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { SchemaMissing } from './SchemaMissing'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const ID = 'aaaaaaaa-0000-4000-8000-0000000000aa'
let deleted: boolean

beforeEach(() => {
  deleted = true
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === `/api/schemas/${ID}/restore-plan`)
        return deleted
          ? json({
              kind: 'schema',
              id: ID,
              name: 'thing',
              records: 3,
              blocked_by: null,
              blocked: null,
              collection: null,
              collection_id: null,
              schema_name: null,
              deleted_at: '2026-03-04T10:00:00Z',
              can_restore: true,
            })
          : json({ detail: "Schema 'x' is not deleted" }, 422)
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
          <SchemaMissing id={ID} message="Schema not found" />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('SchemaMissing', () => {
  it('says a deleted schema was deleted, when, and that it can be restored', async () => {
    renderIt()
    expect(
      await screen.findByText(/“thing” was deleted on .*It can be restored/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/the 3 records deleted with it/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restore…' })).toBeInTheDocument()
  })

  it('is just the error for a schema that was never there', async () => {
    deleted = false
    renderIt()
    expect(await screen.findByText('Schema not found')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Restore…' })).toBeNull()
  })
})
