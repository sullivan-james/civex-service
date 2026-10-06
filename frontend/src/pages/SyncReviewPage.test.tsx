import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SyncConflict } from '../api/remote'
import SyncReviewPage from './SyncReviewPage'

function conflict(n: number, extra: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id: `c${n}`,
    kind: 'conflict',
    entity_type: 'record',
    entity_id: `r${n}`,
    field: 'data.f1',
    yours: `mine ${n}`,
    theirs: `theirs ${n}`,
    base: 'x',
    theirs_actor: 'laptop',
    theirs_at: '2026-10-05T10:00:00Z',
    device_name: null,
    message: null,
    status: 'open',
    created_at: `2026-10-05T10:0${n}:00Z`,
    resolved_at: null,
    resolution: null,
    record_name: `Dive ${n}`,
    dataset_name: 'study',
    schema_name: 'encounter',
    field_label: 'Site',
    dtype: 'string',
    current: `theirs ${n}`,
    stale: false,
    record_deleted: false,
    takes: ['theirs', 'mine', 'value'],
    also_saved: [],
    attempted: null,
    changes: [],
    ...extra,
  }
}

let open: SyncConflict[]
let resolves: { path: string; body: unknown }[]
let reopened: string[][]

beforeEach(() => {
  open = [conflict(1), conflict(2), conflict(3)]
  resolves = []
  reopened = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url)
      const json = (b: unknown) =>
        new Response(JSON.stringify(b), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      if (path.includes('/conflicts?')) return json(open)
      if (path.endsWith('/conflicts/resolve-many')) {
        const body = JSON.parse(String(init?.body)) as {
          take: string
          ids?: string[]
          kind?: string
          record_id?: string
          dry_run?: boolean
        }
        resolves.push({ path, body })
        const matching = open.filter(
          (c) =>
            (!body.ids || body.ids.includes(c.id)) &&
            (!body.kind || c.kind === body.kind) &&
            (!body.record_id || c.entity_id === body.record_id),
        )
        const offered = matching.filter((c) =>
          c.takes.includes(body.take as never),
        )
        // A value that changed again is refused, as the server does.
        const failed = offered.filter(
          (c) => c.id === 'c2' && body.take === 'mine',
        )
        const done = offered.filter((c) => !failed.includes(c))
        if (!body.dry_run) open = open.filter((c) => !done.includes(c))
        return json({
          done: done.length,
          settled_ids: body.dry_run ? [] : done.map((c) => c.id),
          not_offered: matching.length - offered.length,
          failed: failed.map((c) => ({
            id: c.id,
            message: 'Site has changed',
          })),
        })
      }
      if (path.endsWith('/conflicts/reopen')) {
        const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
        reopened.push(ids)
        return json({ reopened: ids.length })
      }
      if (path.endsWith('/resolve')) {
        const body = JSON.parse(String(init?.body))
        resolves.push({ path, body })
        const parts = path.split('/')
        const id = parts[parts.length - 2]
        // A value that changed again is refused, as the server does.
        if (id === 'c2' && body.take === 'mine')
          return new Response(JSON.stringify({ detail: 'Site has changed' }), {
            status: 409,
            headers: { 'Content-Type': 'application/json' },
          })
        open = open.filter((c) => c.id !== id)
        return json({})
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const l = useLocation()
  return <output aria-label="where">{l.pathname + l.search}</output>
}

function page(at = '/sync/review') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[at]}>
        <SyncReviewPage />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SyncReviewPage', () => {
  it('lists them, each record linking to its side-by-side page', async () => {
    page()
    expect(await screen.findByRole('link', { name: 'Dive 1' })).toHaveAttribute(
      'href',
      '/records/r1?tab=resolve',
    )
    expect(screen.getAllByRole('link', { name: /Dive/ })).toHaveLength(3)
    expect(screen.getAllByRole('link', { name: 'Resolve' })).toHaveLength(3)
  })

  it('says so when there is nothing to review', async () => {
    open = []
    page()
    expect(await screen.findByText('Nothing to review')).toBeInTheDocument()
  })

  it('starts a review at the first record, and remembers the order for the stepper', async () => {
    page()
    await userEvent.click(
      await screen.findByRole('button', { name: /Start review/ }),
    )
    expect(screen.getByLabelText('where')).toHaveTextContent(
      '/records/r1?tab=resolve',
    )
    expect(
      JSON.parse(sessionStorage.getItem('civex.syncReview') ?? '[]'),
    ).toEqual([
      { id: 'r1', name: 'Dive 1' },
      { id: 'r2', name: 'Dive 2' },
      { id: 'r3', name: 'Dive 3' },
    ])
  })

  it('settles several at once from the ticked rows, in one request, and says which could not be', async () => {
    page()
    const table = await screen.findByRole('table')
    await userEvent.click(within(table).getByLabelText('Select all'))
    await userEvent.click(screen.getByRole('button', { name: /Use mine/ }))
    await waitFor(() => expect(resolves).toHaveLength(1))
    expect(resolves[0].body).toEqual({ take: 'mine', ids: ['c1', 'c2', 'c3'] })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '1 could not be settled',
    )
    expect(open.map((c) => c.id)).toEqual(['c2'])
  })

  it('only counts the rows that offer an action', async () => {
    open = [
      conflict(1),
      conflict(2, {
        kind: 'rejected',
        takes: ['theirs', 'retry'],
        field: null,
      }),
    ]
    page()
    const table = await screen.findByRole('table')
    await userEvent.click(within(table).getByLabelText('Select all'))
    expect(screen.getByRole('button', { name: 'Use mine (1)' })).toBeEnabled()
  })

  it('keeps theirs for all of them after saying how many, and can undo it', async () => {
    page()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Keep theirs for all' }),
    )
    expect(await screen.findByText(/for 3 changes/)).toBeInTheDocument()
    expect(resolves[0].body).toMatchObject({ take: 'theirs', dry_run: true })
    expect(open).toHaveLength(3)

    await userEvent.click(
      screen.getByRole('button', { name: 'Keep theirs for 3' }),
    )
    expect(await screen.findByText('Nothing to review')).toBeInTheDocument()
    // Settled by what was asked for, not by the ids that happened to be loaded.
    expect(resolves[1].body).toEqual({ take: 'theirs' })

    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(reopened).toEqual([['c1', 'c2', 'c3']]))
  })

  it('narrows by kind, and a bulk action covers only what is shown', async () => {
    open = [
      conflict(1),
      conflict(2, {
        kind: 'rejected',
        takes: ['theirs', 'retry'],
        field: null,
      }),
    ]
    page()
    await userEvent.selectOptions(
      await screen.findByLabelText('Show'),
      'rejected',
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Keep theirs for these' }),
    )
    await userEvent.click(
      await screen.findByRole('button', { name: 'Keep theirs for 1' }),
    )
    await waitFor(() =>
      expect(resolves[1].body).toEqual({ take: 'theirs', kind: 'rejected' }),
    )
    expect(open.map((c) => c.id)).toEqual(['c1'])
  })

  it('settles in the row what has no record page to settle it on', async () => {
    open = [
      conflict(1, {
        entity_type: 'schema',
        kind: 'rejected',
        field: null,
        takes: ['theirs', 'retry'],
      }),
    ]
    page()
    expect(
      await screen.findByRole('button', { name: 'Send again' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Resolve' })).toBeNull()
  })
})
