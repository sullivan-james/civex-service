import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { WorkflowJob } from '../../api/workflows'
import RecordsTouched from './RecordsTouched'

const job = (over: Partial<WorkflowJob> = {}): WorkflowJob => ({
  id: 'j2',
  workflow_name: 'compute',
  record_id: 'r0',
  schema_name: 'Selection',
  trigger: 'manual',
  status: 'completed',
  error: null,
  error_details: null,
  log: null,
  step_executions: null,
  affected_records: [],
  created_at: '2026-10-04T10:00:00Z',
  started_at: '2026-10-04T10:00:01Z',
  finished_at: '2026-10-04T10:00:02Z',
  depth: 0,
  trigger_detail: null,
  ...over,
})

let labelCalls: string[][]
let live: Record<string, string>

beforeEach(() => {
  labelCalls = []
  live = {}
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/records/labels') {
        const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
        labelCalls.push(ids)
        return new Response(
          JSON.stringify(
            ids
              .filter((i) => i in live)
              .map((i) => ({
                id: i,
                schema_name: 'Selection',
                natural_name: live[i],
                deleted: false,
              })),
          ),
          { headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response('{}', {
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

const renderIt = (j: WorkflowJob) =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <RecordsTouched job={j} />
      </MemoryRouter>
    </QueryClientProvider>,
  )

describe('RecordsTouched', () => {
  it('names the records as they are now, not as a copy taken at the time, in one request', async () => {
    live = { r1: 'Selection 1', r2: 'Selection 2', r3: 'Selection 3' }
    renderIt(
      job({
        affected_records: [
          // Older runs kept a name; it was the schema's, the same for all.
          {
            record_id: 'r1',
            schema_name: 'Selection',
            natural_name: 'Selection',
            action: 'updated',
          },
          {
            record_id: 'r2',
            schema_name: 'Selection',
            natural_name: 'Selection',
            action: 'updated',
          },
          {
            record_id: 'r3',
            schema_name: 'Selection',
            natural_name: null,
            action: 'created',
          },
        ],
      }),
    )

    expect(
      await screen.findByRole('link', { name: 'Selection 1' }),
    ).toHaveAttribute('href', '/records/r1')
    expect(
      screen.getByRole('link', { name: 'Selection 2' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Selection 3' }),
    ).toBeInTheDocument()
    expect(labelCalls).toHaveLength(1)
    expect(labelCalls[0].sort()).toEqual(['r1', 'r2', 'r3'])
  })

  it('says whether each was created or updated', async () => {
    live = { r1: 'Selection 1', r2: 'Selection 2' }
    renderIt(
      job({
        affected_records: [
          { record_id: 'r1', schema_name: 'Selection', action: 'created' },
          { record_id: 'r2', schema_name: 'Selection', action: 'updated' },
        ],
      }),
    )

    await screen.findByRole('link', { name: 'Selection 1' })
    expect(screen.getByText('created')).toBeInTheDocument()
    expect(screen.getByText('updated')).toBeInTheDocument()
  })

  it("keeps an older run's stored name for a record that no longer exists, without linking to it", async () => {
    renderIt(
      job({
        affected_records: [
          {
            record_id: 'gone',
            schema_name: 'Selection',
            natural_name: 'Selection 9',
            action: 'updated',
          },
        ],
      }),
    )

    await waitFor(() => expect(labelCalls).toHaveLength(1))
    // Its name is kept, but there is no page to open: it says what became of
    // it, and where to see what happened.
    expect(await screen.findByText('Selection 9')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Selection 9' })).toBeNull()
    expect(
      await screen.findByRole('link', {
        name: /permanently deleted: see history/,
      }),
    ).toBeInTheDocument()
  })

  it('shows the start of the id for a record with no name anywhere', async () => {
    renderIt(
      job({
        affected_records: [
          {
            record_id: 'abcdef12-0000-4000-8000-000000000000',
            schema_name: 'Selection',
            action: 'created',
          },
        ],
      }),
    )

    expect(screen.getByRole('link', { name: 'abcdef12…' })).toBeInTheDocument()
    await waitFor(() => expect(labelCalls).toHaveLength(1))
  })

  it('says plainly when a run touched no records, by how it ended', () => {
    const { unmount } = renderIt(job({ status: 'completed' }))
    expect(
      screen.getByText(/didn't create or change any records/),
    ).toBeInTheDocument()
    unmount()

    const second = renderIt(job({ status: 'cancelled' }))
    expect(screen.getByText(/before this run was stopped/)).toBeInTheDocument()
    second.unmount()

    const third = renderIt(job({ status: 'failed' }))
    expect(screen.getByText(/before this run failed/)).toBeInTheDocument()
    third.unmount()

    renderIt(job({ status: 'running' }))
    expect(screen.getByText('Running…')).toBeInTheDocument()
  })
})
