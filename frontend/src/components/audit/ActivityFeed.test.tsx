import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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
let restoreSelectedBody: unknown

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
    fields: 0,
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
      if (url.pathname === '/api/records/restore-selected') {
        restoreSelectedBody = JSON.parse(String(init?.body))
        return json({ restored: 1, came_back: 1, left: 0 })
      }
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
    events = [single]
    renderFeed()
    await screen.findByText('Deleted now')
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/records/r1/restore-plan')).toBe(
      true,
    )
  })

  it('leads each row with who made the change, then what happened, then when', async () => {
    events = [
      { ...single, id: 'a', entry: entry({ id: 'a', actor: 'alice' }) },
      { ...single, id: 'b', entry: entry({ id: 'b', actor: 'alice' }) },
    ]
    renderFeed()
    await screen.findAllByText('Deleted now')
    const headers = screen
      .getAllByRole('columnheader')
      .map((h) => h.textContent?.trim())
      .filter(Boolean)
    expect(headers.slice(0, 3)).toEqual(['Who', 'What happened', 'When'])
    expect(screen.getAllByText('alice')).toHaveLength(2)
  })

  it('names the person behind a bulk change too, and a dash when it was not recorded', async () => {
    events = [
      { ...batch, id: 'bb', actor: 'bob' },
      { ...single, id: 'old', entry: entry({ id: 'old' }) },
    ]
    renderFeed()
    await screen.findByText('Deleted 1,204 records')
    expect(screen.getByText('bob')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('restores a deleted field from its row, on the schema it came from', async () => {
    events = [
      {
        ...single,
        entry: entry({
          id: 'fe1',
          entity_type: 'field',
          entity_id: 'f1f1f1f1-0000-4000-8000-000000000001',
          old_data: { name: 'note', schema_id: 's1' },
          changes: [],
          now: {
            kind: 'field',
            ref: 'f1f1f1f1-0000-4000-8000-000000000001',
            status: 'deleted',
            name: 'note',
            schema_name: 'thing',
            collection: null,
            deleted_at: '2026-03-04T10:00:00Z',
          },
        }),
      },
    ]
    renderFeed()
    await screen.findByText('Deleted now')
    // A deleted field has no page of its own to link to.
    expect(screen.queryByRole('link', { name: 'note' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(
      calls.some(
        (c) =>
          c.path ===
          '/api/schemas/thing/fields/f1f1f1f1-0000-4000-8000-000000000001/restore-plan',
      ),
    ).toBe(true)
  })

  it('undoes a whole bulk delete from its one line, after saying what comes back', async () => {
    events = [batch]
    restoreAll = {
      collections: 0,
      schemas: 0,
      fields: 0,
      records: 1204,
      things: 1204,
      restores: 1204,
      blocked: 0,
      truncated: false,
    }
    renderFeed()
    await screen.findByText('Deleted 1,204 records')
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('1,204 records')
    expect(dialog).toHaveTextContent('parent first')
    // The plan is for this one delete, not everything that is deleted.
    const planCall = calls.find((c) => c.path === '/api/audit/restore-all')!
    expect(planCall.params.get('batch')).toBe('b1')

    await userEvent.click(screen.getByRole('button', { name: 'Restore all' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && c.path === '/api/audit/restore-all',
        ),
      ).toBe(true),
    )
  })

  it('lets some of a bulk delete come back instead of all of it', async () => {
    events = [batch]
    restoreAll = {
      collections: 0,
      schemas: 0,
      fields: 0,
      records: 1204,
      things: 1204,
      restores: 1204,
      blocked: 0,
      truncated: false,
    }
    renderFeed()
    await screen.findByText('Deleted 1,204 records')
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
    // The one-click restore stays, and so does a way to choose.
    await userEvent.click(
      await screen.findByRole('button', { name: 'Choose which…' }),
    )

    const dialog = await screen.findByRole('dialog', {
      name: /Deleted 1,204 records/,
    })
    expect(dialog).toHaveTextContent('Tick the records to bring back')
    await userEvent.click(
      await within(dialog).findByRole('checkbox', {
        name: 'Select this record',
      }),
    )
    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Restore 1 selected' }),
    )

    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === 'POST' && c.path === '/api/records/restore-selected',
        ),
      ).toBe(true),
    )
    expect(restoreSelectedBody).toEqual({ ids: ['r1'], with_parents: true })
  })

  it('says so when nothing from a bulk delete is still deleted', async () => {
    events = [batch]
    renderFeed()
    await screen.findByText('Deleted 1,204 records')
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
    expect(
      await screen.findByText(/Nothing from this delete is still deleted/),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Restore all' })).toBeNull()
  })

  it("offers the same undo inside the bulk delete's window", async () => {
    events = [batch]
    renderFeed()
    await userEvent.click(await screen.findByText('Deleted 1,204 records'))
    expect(
      await screen.findByRole('button', { name: 'Restore everything…' }),
    ).toBeInTheDocument()
  })

  it('offers to restore everything the Deleted view lists, after saying what it does', async () => {
    restoreAll = {
      collections: 1,
      schemas: 0,
      fields: 0,
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
