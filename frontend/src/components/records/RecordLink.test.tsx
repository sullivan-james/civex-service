import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { RecordLink } from './RecordLink'
import { RecordMissing } from './RecordMissing'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

const LIVE = 'aaaaaaaa-0000-4000-8000-000000000001'
const DELETED = 'bbbbbbbb-0000-4000-8000-000000000002'
const GONE = 'cccccccc-0000-4000-8000-000000000003'

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/records/labels') {
        const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
        // A record that no longer exists is simply left out, as the server does.
        return json(
          ids
            .filter((id) => id !== GONE)
            .map((id) => ({
              id,
              schema_name: 'Selection',
              natural_name: id === LIVE ? 'Selection 26' : 'Selection 27',
              deleted: id === DELETED,
              deleted_at: id === DELETED ? '2026-03-04T10:00:00Z' : null,
            })),
        )
      }
      if (url.pathname === `/api/records/${DELETED}/restore-plan`)
        return json({
          kind: 'record',
          id: DELETED,
          name: 'Selection 27',
          records: 1,
          blocked_by: { kind: 'schema', id: 's1', name: 'selection' },
          blocked:
            "'Selection 27' is typed by the schema 'selection', which is deleted. Restore that first.",
          can_restore: false,
          collection: 'study',
          collection_id: 'c1',
          schema_name: null,
          deleted_at: '2026-03-04T10:00:00Z',
        })
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderIn(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RecordLink', () => {
  it('links a record that exists to its page', async () => {
    renderIn(<RecordLink id={LIVE} />)
    const link = await screen.findByRole('link', { name: 'Selection 26' })
    expect(link).toHaveAttribute('href', `/records/${LIVE}`)
  })

  it('does not link a deleted record to a page that is not there, and says where to look', async () => {
    renderIn(<RecordLink id={DELETED} />)
    expect(await screen.findByText('Selection 27')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Selection 27' })).toBeNull()
    const history = await screen.findByRole('link', {
      name: /deleted: see history/,
    })
    expect(history.getAttribute('href')).toContain('/activity?activity.filter=')
    expect(decodeURIComponent(history.getAttribute('href')!)).toContain(DELETED)
  })

  it('says a record that no longer exists is permanently deleted, using the name it kept', async () => {
    renderIn(<RecordLink id={GONE} fallback="Selection 99" />)
    expect(await screen.findByText('Selection 99')).toBeInTheDocument()
    expect(
      await screen.findByRole('link', {
        name: /permanently deleted: see history/,
      }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Selection 99' })).toBeNull()
  })

  it('falls back to the start of the id when there is no name at all', async () => {
    renderIn(<RecordLink id={GONE} />)
    expect(await screen.findByText('cccccccc…')).toBeInTheDocument()
  })
})

describe('RecordMissing', () => {
  it('says when a deleted record was deleted and offers to restore it', async () => {
    renderIn(<RecordMissing id={DELETED} />)
    expect(
      await screen.findByText(
        /This record was deleted on .* It can be restored/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restore…' })).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'See what happened to it' }),
    ).toBeInTheDocument()
  })

  it('says when a deleted record went with its deleted schema', async () => {
    renderIn(<RecordMissing id={DELETED} />)
    expect(
      await screen.findByText(/typed by the schema .*selection.*deleted too/),
    ).toBeInTheDocument()
  })

  it('says a record that is gone may have been permanently deleted', async () => {
    renderIn(<RecordMissing id={GONE} />)
    expect(
      await screen.findByText(/may have been permanently deleted/),
    ).toBeInTheDocument()
  })
})
