import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
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
    ...extra,
  }
}

let open: SyncConflict[]
let resolves: { path: string; body: unknown }[]

beforeEach(() => {
  open = [conflict(1), conflict(2), conflict(3)]
  resolves = []
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

function page(at = '/sync/review') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[at]}>
        <SyncReviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SyncReviewPage', () => {
  it('steps through them one at a time, with a count', async () => {
    page()
    expect(await screen.findByText('1 of 3')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dive 1' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText('2 of 3')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dive 2' })).toBeInTheDocument()
    await userEvent.keyboard('{ArrowLeft}')
    expect(await screen.findByText('1 of 3')).toBeInTheDocument()
  })

  it('moves on to the next one once this is settled', async () => {
    page()
    await screen.findByText('1 of 3')
    await userEvent.click(screen.getByRole('button', { name: 'Keep theirs' }))
    expect(await screen.findByText('1 of 2')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dive 2' })).toBeInTheDocument()
  })

  it('says so when there is nothing to review', async () => {
    open = []
    page()
    expect(await screen.findByText('Nothing to review')).toBeInTheDocument()
  })

  it('settles several at once from the list, and says which could not be', async () => {
    page('/sync/review?mode=list')
    const table = await screen.findByRole('table')
    await userEvent.click(within(table).getByLabelText('Select all'))
    await userEvent.click(screen.getByRole('button', { name: /Use mine/ }))
    await waitFor(() => expect(resolves).toHaveLength(3))
    expect(
      resolves.every((r) => (r.body as { take: string }).take === 'mine'),
    ).toBe(true)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '1 could not be settled',
    )
    // The one that was refused is still there to look at.
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
    page('/sync/review?mode=list')
    const table = await screen.findByRole('table')
    await userEvent.click(within(table).getByLabelText('Select all'))
    expect(screen.getByRole('button', { name: 'Use mine (1)' })).toBeEnabled()
  })
})
