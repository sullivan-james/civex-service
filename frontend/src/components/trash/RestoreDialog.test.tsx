import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { RestorePlan } from '../../api/restore'
import { ToastProvider } from '../ui/ToastProvider'
import { RestoreDialog } from './RestoreDialog'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const plan = (over: Partial<RestorePlan> = {}): RestorePlan => ({
  kind: 'record',
  id: 'rec-1',
  name: 'Sample 12',
  records: 1,
  blocked_by: null,
  blocked: null,
  collection: 'study',
  collection_id: 'col-1',
  can_restore: true,
  ...over,
})

let plans: Record<string, RestorePlan>
let calls: { method: string; path: string }[]
const onClose = vi.fn()

function renderDialog(kind: 'record' | 'collection' | 'schema', ref: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <RestoreDialog target={{ kind, ref }} onClose={onClose} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  plans = {}
  calls = []
  onClose.mockReset()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({ method, path: url.pathname })
      if (method === 'GET' && url.pathname.endsWith('/restore-plan')) {
        const found = plans[url.pathname]
        return found ? json(found) : json({ detail: 'not found' }, 404)
      }
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('RestoreDialog', () => {
  it('says where a record goes, then restores and reports it', async () => {
    plans['/api/records/rec-1/restore-plan'] = plan({ records: 3 })
    renderDialog('record', 'rec-1')

    expect(await screen.findByText(/goes back to study/)).toHaveTextContent(
      'along with 2 records deleted with it',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))

    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && c.path === '/api/records/rec-1/restore',
        ),
      ).toBe(true),
    )
    // The receipt names what came back, where, and offers a way to see it.
    expect(
      await screen.findByText(
        'Restored "Sample 12" to study, with 2 records deleted alongside it',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View' })).toBeInTheDocument()
    expect(onClose).toHaveBeenCalled()
  })

  it('will not restore a blocked record, and offers the blocker instead', async () => {
    plans['/api/records/rec-1/restore-plan'] = plan({
      can_restore: false,
      blocked:
        "'Sample 12' is in the collection 'study', which is deleted. Restore that first.",
      blocked_by: { kind: 'collection', id: 'col-1', name: 'study' },
    })
    plans['/api/collections/study/restore-plan'] = plan({
      kind: 'collection',
      id: 'col-1',
      name: 'study',
      records: 1204,
      collection: null,
      collection_id: null,
    })
    renderDialog('record', 'rec-1')

    expect(
      await screen.findByText(/which is deleted. Restore that first/),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Restore' })).toBeNull()

    await userEvent.click(
      screen.getByRole('button', {
        name: /Restore the collection “study” instead/,
      }),
    )
    // The dialog now describes the collection and what comes back with it.
    expect(
      await screen.findByText(/with the 1,204 records deleted with it/),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === 'POST' && c.path === '/api/collections/study/restore',
        ),
      ).toBe(true),
    )
    expect(
      await screen.findByText('Restored collection "study" and 1,204 records'),
    ).toBeInTheDocument()
  })

  it('can step back from the blocker to the record', async () => {
    plans['/api/records/rec-1/restore-plan'] = plan({
      can_restore: false,
      blocked: 'blocked',
      blocked_by: { kind: 'schema', id: 's1', name: 'trial' },
    })
    plans['/api/schemas/trial/restore-plan'] = plan({
      kind: 'schema',
      name: 'trial',
      records: 2,
    })
    renderDialog('record', 'rec-1')
    await userEvent.click(
      await screen.findByRole('button', { name: /Restore the schema/ }),
    )
    await screen.findByText(/with the 2 records/)
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByText('blocked')).toBeInTheDocument()
  })

  it('shows a plan that cannot be fetched', async () => {
    renderDialog('record', 'missing')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
