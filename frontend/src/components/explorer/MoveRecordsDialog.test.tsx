import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { RecordMovePlan } from '../../api/records'
import type { Schema } from '../../api/schemas'
import { ToastProvider } from '../ui/ToastProvider'
import { MoveRecordsDialog, type MoveSelection } from './MoveRecordsDialog'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

function schema(name: string, parent: Schema | null): Schema {
  return {
    id: `id-${name}`,
    name,
    label: null,
    description: null,
    parent_id: parent?.id ?? null,
    display_template: null,
    deleted_at: null,
    fields: [],
  }
}
const site = schema('site', null)
const visit = schema('visit', site)
const SCHEMAS = [site, visit]

const collection = (name: string) => ({
  id: `c-${name}`,
  name,
  description: null,
  timezone: null,
  record_count: 1,
  deleted_at: null,
  scope: 'local',
})

const plan = (over: Partial<RecordMovePlan> = {}): RecordMovePlan => ({
  collection: 'archive',
  collection_id: 'c-archive',
  parent_id: null,
  parent_name: null,
  roots: 2,
  records: 5,
  skipped: 0,
  sources: ['survey'],
  problems: [],
  can_move: true,
  ...over,
})

let plans: RecordMovePlan
let calls: { method: string; path: string; body?: unknown }[]
const onClose = vi.fn()
const onMoved = vi.fn()

function renderDialog(selection: MoveSelection, listed: Schema = site) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <MoveRecordsDialog
            selection={selection}
            count={2}
            listed={listed}
            schemas={SCHEMAS}
            from="survey"
            onClose={onClose}
            onMoved={onMoved}
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  plans = plan()
  calls = []
  onClose.mockReset()
  onMoved.mockReset()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: url.pathname,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (url.pathname === '/api/collections')
        return json([collection('survey'), collection('archive')])
      if (url.pathname === '/api/records/move/plan') return json(plans)
      if (url.pathname === '/api/records/move')
        return json({ roots: 2, records: 5, collection: 'archive' })
      if (url.pathname.endsWith('/records'))
        return json({
          items: [
            {
              id: 'p1',
              dataset_id: 'c-archive',
              schema_name: 'site',
              parent_record_id: null,
              data: {},
              natural_name: 'North',
              created_at: '',
              updated_at: '',
              deleted_at: null,
            },
          ],
          total: 1,
          offset: 0,
          limit: 20,
        })
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('MoveRecordsDialog', () => {
  it('asks the server what the move would do and then does exactly that', async () => {
    const user = userEvent.setup()
    renderDialog({ ids: ['a', 'b'] })

    // Another collection is chosen by default, and the plan is for it.
    await screen.findByText(/5 records would move to archive/)
    expect(
      screen.getByText(/2 chosen records with everything inside/),
    ).toBeInTheDocument()
    const planned = calls.find((c) => c.path === '/api/records/move/plan')!
    expect(planned.body).toEqual({
      to: 'archive',
      parent: null,
      ids: ['a', 'b'],
    })

    await user.click(screen.getByRole('button', { name: 'Move 5' }))
    await waitFor(() => expect(onMoved).toHaveBeenCalled())
    const moved = calls.find((c) => c.path === '/api/records/move')!
    expect(moved.body).toEqual(planned.body)
    expect(onClose).toHaveBeenCalled()
  })

  it('sends the list\'s own query for "all matching"', async () => {
    renderDialog({
      query: { schema: 'site', search: 'north', filter: null },
      collection: 'survey',
    })
    await screen.findByText(/would move to archive/)
    const planned = calls.find((c) => c.path === '/api/records/move/plan')!
    expect(planned.body).toMatchObject({
      to: 'archive',
      collection: 'survey',
      schema_name: 'site',
      search: 'north',
    })
  })

  it('shows what is in the way and offers no Move', async () => {
    plans = plan({
      can_move: false,
      problems: ['1 record in ‘survey’ references records being moved.'],
    })
    renderDialog({ ids: ['a'] })
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Move 5' })).toBeDisabled()
  })

  it('needs a record to go inside for a kind that nests', async () => {
    const user = userEvent.setup()
    renderDialog({ ids: ['v1'] }, visit)
    expect(
      await screen.findByText(/Choose where the records go/),
    ).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/records/move/plan')).toBe(false)
    // The picker searches the target collection, so wait for it to be chosen.
    await waitFor(() =>
      expect(
        screen.getByRole('combobox', { name: 'To collection' }),
      ).toHaveValue('archive'),
    )

    const picker = screen.getByRole('textbox', { name: 'Inside which site' })
    await user.click(picker)
    await user.click(await screen.findByText('North'))
    await screen.findByText(/would move to archive/)
    const planned = calls.find((c) => c.path === '/api/records/move/plan')!
    expect(planned.body).toEqual({ to: 'archive', parent: 'p1', ids: ['v1'] })
    // The parent was searched for in the target collection, not the current one.
    expect(
      calls.some(
        (c) =>
          c.method === 'GET' && c.path === '/api/collections/archive/records',
      ),
    ).toBe(true)
  })
})
