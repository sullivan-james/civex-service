import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { BulkEditPlan, RecordSelection } from '../../api/records'
import type { Field, Schema } from '../../api/schemas'
import { ToastProvider } from '../ui/ToastProvider'
import { BulkEditDialog } from './BulkEditDialog'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const field = (
  name: string,
  type: string,
  over: Partial<Field> = {},
): Field => ({
  id: `f-${name}`,
  name,
  label: null,
  type,
  required: false,
  restrictions: {},
  default: null,
  position: null,
  ...over,
})

const sample: Schema = {
  id: 's-sample',
  name: 'sample',
  label: null,
  description: null,
  parent_id: null,
  display_template: null,
  deleted_at: null,
  fields: [
    field('status', 'string'),
    field('depth', 'integer'),
    field('photo', 'file'),
  ],
}

const plan = (over: Partial<BulkEditPlan> = {}): BulkEditPlan => ({
  fields: ['status'],
  records: 5,
  changing: 3,
  unchanged: 1,
  skipped: 1,
  skipped_records: [{ record_id: 'r5', name: 'S5', reason: 'Too deep' }],
  runs: 3,
  workflows: ['on_status'],
  automation_paused: false,
  can_apply: true,
  ...over,
})

let plans: BulkEditPlan
let calls: { method: string; path: string; body?: unknown }[]
const onClose = vi.fn()
const onDone = vi.fn()

function renderDialog(selection: RecordSelection) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <BulkEditDialog
            selection={selection}
            count={5}
            listed={sample}
            onClose={onClose}
            onDone={onDone}
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
  onDone.mockReset()
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
      if (url.pathname === '/api/records/bulk-edit/plan') return json(plans)
      if (url.pathname === '/api/records/bulk-edit')
        return json({
          changed: 3,
          unchanged: 1,
          skipped: 1,
          skipped_records: [],
          runs: 3,
        })
      if (url.pathname.startsWith('/api/file-access/progress'))
        return json({}, 404)
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('BulkEditDialog', () => {
  it('offers the kind’s own fields but not files', () => {
    renderDialog({ ids: ['a'] })
    const options = [
      ...screen
        .getByRole('combobox', { name: 'Field' })
        .querySelectorAll('option'),
    ].map((o) => o.textContent)
    expect(options).toEqual(['Status', 'Depth'])
  })

  it('shows the server’s plan for the value and then makes exactly that edit', async () => {
    const user = userEvent.setup()
    renderDialog({ ids: ['a', 'b'] })
    await user.type(screen.getByRole('textbox'), 'checked')

    await screen.findByText(/3 records would change/)
    expect(
      screen.getByText(/1 record already has this value/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Too deep/)).toBeInTheDocument()
    expect(screen.getByText(/3 workflow runs would start/)).toBeInTheDocument()
    const planned = calls.filter(
      (c) => c.path === '/api/records/bulk-edit/plan',
    )
    expect(planned[planned.length - 1].body).toEqual({
      ids: ['a', 'b'],
      changes: { status: 'checked' },
    })

    await user.click(screen.getByRole('button', { name: 'Change 3' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const sent = calls.find((c) => c.path === '/api/records/bulk-edit')!
    expect(sent.body).toEqual({
      ids: ['a', 'b'],
      changes: { status: 'checked' },
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('clears a field and sends the list’s query for all matching', async () => {
    const user = userEvent.setup()
    renderDialog({
      query: { schema: 'sample', search: 'reef' },
      collection: 'survey',
    })
    await user.click(screen.getByRole('radio', { name: 'Clear' }))
    await screen.findByText(/3 records would change/)
    const planned = calls.filter(
      (c) => c.path === '/api/records/bulk-edit/plan',
    )
    expect(planned[planned.length - 1].body).toMatchObject({
      collection: 'survey',
      schema_name: 'sample',
      search: 'reef',
      changes: { status: null },
    })
  })

  it('offers nothing to change when nothing would', async () => {
    plans = plan({
      changing: 0,
      unchanged: 5,
      skipped: 0,
      runs: 0,
      can_apply: false,
    })
    const user = userEvent.setup()
    renderDialog({ ids: ['a'] })
    await user.type(screen.getByRole('textbox'), 'x')
    await screen.findByText(/Nothing would change/)
    expect(screen.getByRole('button', { name: 'Change' })).toBeDisabled()
  })
})
