import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RecordConflicts } from './RecordConflicts'

let conflictCalls: number

function conflict(id: string, entity: string) {
  return {
    id,
    kind: 'conflict',
    entity_type: 'record',
    entity_id: entity,
    field: 'data.f1',
    yours: 'a',
    theirs: 'b',
    base: null,
    theirs_actor: null,
    theirs_at: null,
    device_name: null,
    message: null,
    status: 'open',
    created_at: '2026-10-05T10:00:00Z',
    resolved_at: null,
    resolution: null,
    record_name: 'Dive',
    dataset_name: 'study',
    schema_name: 'encounter',
    field_label: 'Site',
    dtype: 'string',
    current: 'b',
    stale: false,
    record_deleted: false,
    takes: ['theirs', 'mine'],
    also_saved: [],
  }
}

function serve(open: number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const path = String(url)
      const json = (b: unknown) =>
        new Response(JSON.stringify(b), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      if (path.includes('/conflicts?')) {
        conflictCalls++
        return json([conflict('c1', 'r1'), conflict('c2', 'other')])
      }
      return json({
        configured: true,
        open_conflicts: open,
        pending: 0,
        running: false,
      })
    }),
  )
}

function show() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <RecordConflicts recordId="r1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  conflictCalls = 0
})
afterEach(() => vi.unstubAllGlobals())

describe('RecordConflicts', () => {
  it('shows only this record’s conflicts, with the choices inline', async () => {
    serve(2)
    show()
    expect(
      await screen.findByText(
        '1 of your changes to this record was not applied',
      ),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Use mine' })).toBeInTheDocument()
  })

  it('says nothing, and asks for nothing, while there is nothing to review', async () => {
    serve(0)
    show()
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByRole('region')).toBeNull()
    expect(conflictCalls).toBe(0)
  })
})
