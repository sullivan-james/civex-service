import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { AuditLogEntry, RevertPlan } from '../../api/audit'
import { ToastProvider } from '../ui/ToastProvider'
import { describeAuditEntry } from '../../utils/recordAudit'
import { AuditTrail } from './AuditTrail'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const ENTRY_ID = '11111111-0000-4000-8000-000000000001'

const update: AuditLogEntry = {
  id: ENTRY_ID,
  commit_id: null,
  action: 'update',
  entity_type: 'record',
  entity_id: '22222222-0000-4000-8000-000000000002',
  old_data: null,
  new_data: null,
  timestamp: '2026-01-01T12:00:00Z',
  now: null,
  changes: [
    { field: 'count', label: 'Count', dtype: 'integer', before: 1, after: 2 },
    {
      field: 'note',
      label: 'Note',
      dtype: 'string',
      before: null,
      after: 'hi',
    },
  ],
}

const plan = (over: Partial<RevertPlan> = {}): RevertPlan => ({
  audit_id: ENTRY_ID,
  entity_type: 'record',
  entity_id: update.entity_id,
  kind: 'update',
  blocked: null,
  blocker: null,
  can_apply: true,
  has_conflicts: false,
  fields: [
    {
      field: 'count',
      label: 'Count',
      dtype: 'integer',
      current: 2,
      target: 1,
      status: 'apply',
      reason: null,
    },
  ],
  ...over,
})

let calls: { method: string; path: string; body: unknown }[]
let currentPlan: RevertPlan
let restorePlan: Record<string, unknown>

function renderTrail(entry: AuditLogEntry = update) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <AuditTrail
            queryKey={['records', 'r1', 'audit']}
            fetchPage={async () => ({
              items: [entry],
              total: 1,
              offset: 0,
              limit: 50,
            })}
            describeEntry={describeAuditEntry}
            emptyMessage="Nothing yet."
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  calls = []
  currentPlan = plan()
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
      if (url.pathname === '/api/records/rec-9/restore-plan')
        return json(restorePlan)
      if (url.pathname === `/api/audit/${ENTRY_ID}/revert`) {
        if (method === 'GET') return json(currentPlan)
        return json({
          audit_id: ENTRY_ID,
          entity_id: update.entity_id,
          kind: 'update',
          applied: ['count'],
        })
      }
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('AuditTrail', () => {
  it('summarises what changed on the row', async () => {
    renderTrail()
    const title = await screen.findByText('Record updated')
    expect(title.closest('tr')).toHaveTextContent(
      'Count 1 → 2; Note (none) → hi',
    )
  })

  it('opens the entry in full when the row is clicked', async () => {
    renderTrail()
    await userEvent.click(await screen.findByText('Record updated'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Count')
    expect(dialog).toHaveTextContent('1 → 2')
    expect(dialog).toHaveTextContent('(none) → hi')
  })

  it('previews a revert before doing it, then reverts', async () => {
    renderTrail()
    await userEvent.click(await screen.findByText('Record updated'))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Revert…' }),
    )

    expect(await screen.findByText('Will be put back')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Revert' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
        force: false,
      }),
    )
  })

  it('needs the overwrite box for a field edited since', async () => {
    currentPlan = plan({
      has_conflicts: true,
      fields: [
        {
          field: 'count',
          label: 'Count',
          dtype: 'integer',
          current: 9,
          target: 1,
          status: 'conflict',
          reason: 'Edited since this change.',
        },
      ],
    })
    renderTrail()
    await userEvent.click(await screen.findByText('Record updated'))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Revert…' }),
    )

    const confirm = await screen.findByRole('button', { name: 'Revert' })
    expect(confirm).toBeDisabled()
    await userEvent.click(screen.getByLabelText(/overwrite the fields edited/i))
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
        force: true,
      }),
    )
  })

  it('says why an entry cannot be undone', async () => {
    currentPlan = plan({
      kind: 'update',
      blocked: 'This record is deleted. Restore it first.',
      can_apply: false,
      fields: [],
    })
    renderTrail()
    await userEvent.click(await screen.findByText('Record updated'))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Revert…' }),
    )
    expect(
      await screen.findByText('This record is deleted. Restore it first.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revert' })).toBeDisabled()
  })

  it('restores a deleted record through the restore window, which names what is in the way', async () => {
    restorePlan = {
      kind: 'record',
      id: 'rec-9',
      name: 'Sample 12',
      records: 1,
      blocked_by: { kind: 'collection', id: 'c1', name: 'study' },
      blocked:
        "'Sample 12' is in the collection 'study', which is deleted. Restore that first.",
      collection: 'study',
      collection_id: 'c1',
      can_restore: false,
    }
    renderTrail({
      ...update,
      action: 'delete',
      now: {
        kind: 'record',
        ref: 'rec-9',
        status: 'deleted',
        name: 'Sample 12',
        schema_name: 'Recording',
        collection: 'study',
        deleted_at: null,
      },
    })
    await userEvent.click(await screen.findByText('Record deleted'))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Restore…' }),
    )
    expect(await screen.findByText(/which is deleted/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Restore the collection “study”/ }),
    ).toBeInTheDocument()
  })

  it('offers no restore for a deletion that is already undone', async () => {
    renderTrail({
      ...update,
      action: 'delete',
      now: {
        kind: 'record',
        ref: 'rec-9',
        status: 'live',
        name: 'Sample 12',
        schema_name: 'Recording',
        collection: 'study',
        deleted_at: null,
      },
    })
    await userEvent.click(await screen.findByText('Record deleted'))
    await screen.findByRole('dialog')
    expect(screen.queryByRole('button', { name: 'Restore…' })).toBeNull()
    expect(
      screen.queryByRole('button', { name: /Delete permanently/ }),
    ).toBeNull()
  })

  it('can delete something permanently from its deletion', async () => {
    renderTrail({
      ...update,
      action: 'delete',
      now: {
        kind: 'record',
        ref: 'rec-9',
        status: 'deleted',
        name: 'Sample 12',
        schema_name: 'Recording',
        collection: 'study',
        deleted_at: null,
      },
    })
    await userEvent.click(await screen.findByText('Record deleted'))
    await userEvent.click(
      await screen.findByRole('button', { name: /Delete permanently/ }),
    )
    expect(await screen.findByText(/This cannot be undone/)).toBeInTheDocument()
  })

  it('offers no revert for a schema change', async () => {
    renderTrail({
      ...update,
      entity_type: 'schema',
      changes: [
        {
          field: 'description',
          label: null,
          dtype: null,
          before: null,
          after: 'about',
        },
      ],
    })
    await userEvent.click(await screen.findByText('Record updated'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Description')
    expect(screen.queryByRole('button', { name: 'Revert…' })).toBeNull()
  })
})
