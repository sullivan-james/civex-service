import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { AuditEvent, AuditLogEntry } from '../../api/audit'
import { ToastProvider } from '../ui/ToastProvider'
import { underRecord } from '../../utils/auditFilter'
import { ActivityFeed } from './ActivityFeed'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const FIELDS = [
  {
    name: 'now',
    label: 'Now',
    type: 'enum',
    description: '',
    choices: ['live', 'deleted', 'gone'],
    operators: ['eq', 'ne', 'in'],
  },
  {
    name: 'kind',
    label: 'Kind',
    type: 'enum',
    description: '',
    choices: ['record'],
    operators: ['eq', 'ne', 'in'],
  },
]

const entry = (over: Partial<AuditLogEntry> = {}): AuditLogEntry => ({
  id: 'e1',
  commit_id: null,
  action: 'delete',
  entity_type: 'record',
  entity_id: 'r1',
  old_data: null,
  new_data: null,
  timestamp: '2026-01-01T12:00:00Z',
  changes: [
    {
      field: 'label',
      label: 'Label',
      dtype: 'string',
      before: 'R1',
      after: null,
    },
  ],
  now: {
    kind: 'record',
    ref: 'r1',
    status: 'deleted',
    name: 'R1',
    schema_name: 'recording',
    collection: 'humpback',
    deleted_at: null,
  },
  ...over,
})

const single: AuditEvent = {
  id: 'e1',
  kind: 'entry',
  timestamp: '2026-01-01T12:00:00Z',
  count: 1,
  entry: entry(),
  batch: null,
  parts: [],
}

const batch: AuditEvent = {
  id: 'b1',
  kind: 'batch',
  timestamp: '2026-01-02T12:00:00Z',
  count: 1204,
  entry: null,
  batch: {
    id: 'b1',
    kind: 'delete',
    label: null,
    ref: null,
    created_at: '2026-01-02T12:00:00Z',
  },
  parts: [{ entity_type: 'record', action: 'delete', count: 1204 }],
}

let events: AuditEvent[]
let restoreAll: Record<string, unknown>
let calls: { method: string; path: string; params: URLSearchParams }[]

function renderFeed(scope?: ReturnType<typeof underRecord>, initial = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[initial]}>
          <ActivityFeed scope={scope} emptyMessage="Nothing yet." />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const lastEventsCall = () =>
  [...calls].reverse().find((c) => c.path === '/api/audit/events')!

beforeEach(() => {
  events = [batch, single]
  restoreAll = {
    collections: 0,
    schemas: 0,
    records: 0,
    things: 0,
    restores: 0,
    blocked: 0,
    truncated: false,
  }
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      calls.push({
        method: init?.method ?? 'GET',
        path: url.pathname,
        params: url.searchParams,
      })
      if (url.pathname === '/api/audit/restore-all')
        return init?.method === 'POST'
          ? json({ restored: 3, records: 1206, blocked: 1 })
          : json(restoreAll)
      if (url.pathname === '/api/audit/filter-fields') return json(FIELDS)
      if (url.pathname === '/api/collections') return json([])
      if (url.pathname === '/api/schemas') return json([])
      if (url.pathname === '/api/audit/events')
        return json({
          items: events,
          total: events.length,
          offset: 0,
          limit: 25,
        })
      if (url.pathname === '/api/audit/batches/b1/entries')
        return json({
          items: [entry({ id: 'm1' })],
          total: 1,
          offset: 0,
          limit: 25,
        })
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('ActivityFeed', () => {
  it('shows a bulk operation as one line that says what it did', async () => {
    renderFeed()
    expect(await screen.findByText('Deleted 1,204 records')).toBeInTheDocument()
  })

  it('marks a change to a record that is not there now', async () => {
    renderFeed()
    expect(await screen.findByText('Deleted now')).toBeInTheDocument()
  })

  it('links a live record straight to it and shows its id', async () => {
    events = [
      {
        ...single,
        entry: entry({
          id: 'e2',
          action: 'update',
          entity_id: '4d9362b7-5cf6-4561-a004-7423c358a541',
          now: {
            kind: 'record',
            ref: '4d9362b7-5cf6-4561-a004-7423c358a541',
            status: 'live',
            name: 'Selection 26',
            schema_name: 'Selection',
            collection: 'Test Datas',
            deleted_at: null,
          },
        }),
      },
    ]
    renderFeed()
    const link = await screen.findByRole('link', { name: 'Selection 26' })
    expect(link).toHaveAttribute(
      'href',
      '/records/4d9362b7-5cf6-4561-a004-7423c358a541',
    )
    expect(screen.getByText('4d9362b7')).toBeInTheDocument()
    expect(screen.getByText('in Test Datas')).toBeInTheDocument()
  })

  it('shows a deleted record plainly, with its id, since it has no page', async () => {
    renderFeed()
    await screen.findByText('Deleted now')
    expect(screen.queryByRole('link', { name: 'R1' })).toBeNull()
    expect(screen.getByText('R1')).toBeInTheDocument()
    expect(screen.getByText('r1')).toBeInTheDocument() // its id, short
  })

  it('still says what kind of record it was once it is gone for good', async () => {
    events = [
      {
        ...single,
        entry: entry({
          entity_id: 'abcdef12-0000-4000-8000-000000000000',
          now: {
            kind: 'record',
            ref: null,
            status: 'gone',
            name: null,
            schema_name: 'Selection',
            collection: null,
            deleted_at: null,
          },
        }),
      },
    ]
    renderFeed()
    expect(await screen.findByText('Gone for good')).toBeInTheDocument()
    expect(screen.getByText('Selection')).toBeInTheDocument()
    expect(screen.getByText('abcdef12')).toBeInTheDocument()
  })

  it('writes the whole id when the entry is opened', async () => {
    renderFeed()
    await userEvent.click(await screen.findByText('Record deleted'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('r1')
  })

  it('opens a batch to the changes in it', async () => {
    renderFeed()
    await userEvent.click(await screen.findByText('Deleted 1,204 records'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('1,204 records deleted')
    await waitFor(() => expect(dialog).toHaveTextContent('Record deleted'))
  })

  it('always applies the scope the page is in', async () => {
    renderFeed(underRecord('enc-1'))
    await screen.findByText('Deleted 1,204 records')
    expect(JSON.parse(lastEventsCall().params.get('filter')!)).toEqual({
      field: 'under',
      op: 'eq',
      value: 'enc-1',
    })
  })

  it('narrows to what is deleted in one click, beside the scope', async () => {
    renderFeed(underRecord('enc-1'))
    const button = await screen.findByRole('button', { name: 'Deleted' })
    expect(button).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(button)
    await waitFor(() => {
      const filter = JSON.parse(lastEventsCall().params.get('filter')!)
      expect(filter.and).toEqual([
        { field: 'under', op: 'eq', value: 'enc-1' },
        { field: 'now', op: 'eq', value: 'deleted' },
        { field: 'change', op: 'eq', value: 'delete' },
      ])
    })
    expect(button).toHaveAttribute('aria-pressed', 'true')
    // And off again, leaving the scope.
    await userEvent.click(button)
    await waitFor(() =>
      expect(JSON.parse(lastEventsCall().params.get('filter')!)).toEqual({
        field: 'under',
        op: 'eq',
        value: 'enc-1',
      }),
    )
  })

  it('restores a deleted record from its row', async () => {
    renderFeed()
    await screen.findByText('Deleted now')
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/records/r1/restore-plan')).toBe(
      true,
    )
  })

  it('offers to restore everything the Deleted view lists, after saying what it does', async () => {
    restoreAll = {
      collections: 1,
      schemas: 0,
      records: 2,
      things: 3,
      restores: 1206,
      blocked: 1,
      truncated: false,
    }
    renderFeed()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Deleted' }),
    )
    await userEvent.click(
      await screen.findByRole('button', { name: /Restore all 3/ }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('1,206 records in all')
    expect(dialog).toHaveTextContent('1 stay deleted')
    await userEvent.click(screen.getByRole('button', { name: 'Restore all' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && c.path === '/api/audit/restore-all',
        ),
      ).toBe(true),
    )
  })

  it('sends a search to the server', async () => {
    renderFeed()
    await screen.findByText('Deleted 1,204 records')
    await userEvent.type(
      screen.getByPlaceholderText(/Search values, file names/),
      'selection-017',
    )
    await waitFor(() =>
      expect(lastEventsCall().params.get('q')).toBe('selection-017'),
    )
  })

  it('reads a filter held in the address', async () => {
    const filter = encodeURIComponent(
      JSON.stringify({ field: 'kind', op: 'eq', value: 'record' }),
    )
    renderFeed(undefined, `/?activity.filter=${filter}`)
    await screen.findByText('Deleted 1,204 records')
    expect(JSON.parse(lastEventsCall().params.get('filter')!)).toEqual({
      field: 'kind',
      op: 'eq',
      value: 'record',
    })
  })

  it('says so when nothing matches', async () => {
    events = []
    renderFeed()
    expect(await screen.findByText('No history yet')).toBeInTheDocument()
  })
})
