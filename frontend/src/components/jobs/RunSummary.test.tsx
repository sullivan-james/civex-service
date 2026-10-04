import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router'
import type { WorkflowJob } from '../../api/workflows'
import RunSummary from './RunSummary'

const job = (over: Partial<WorkflowJob> = {}): WorkflowJob => ({
  id: 'j2',
  workflow_name: 'compute',
  record_id: 'r1',
  schema_name: 'Selection',
  trigger: 'record_updated',
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
        <RunSummary job={j} />
      </MemoryRouter>
    </QueryClientProvider>,
  )

describe('RunSummary: what started the run', () => {
  it('shows exactly which fields changed, from what to what', () => {
    renderIt(
      job({
        trigger_detail: {
          caused_by: null,
          changes: [
            {
              field: 'contour_file',
              before: 'old.csv',
              after: 'new.csv',
              watched: true,
            },
            { field: 'duration', before: null, after: '0.341', watched: false },
          ],
        },
      }),
    )

    expect(
      screen.getByText(/because contour_file was updated on this Selection/),
    ).toBeInTheDocument()
    expect(screen.getByText('old.csv → new.csv')).toBeInTheDocument()
    expect(screen.getByText('empty → 0.341')).toBeInTheDocument()
    expect(screen.getByText('what started it')).toBeInTheDocument()
    expect(screen.getByText('also changed')).toBeInTheDocument()
  })

  it('says so when an older run did not record which field changed', () => {
    renderIt(job())
    expect(
      screen.getByText("Which field changed wasn't recorded for this run."),
    ).toBeInTheDocument()
  })

  it('links to the run that started a chained one', () => {
    renderIt(
      job({
        depth: 1,
        trigger_detail: {
          changes: [],
          caused_by: { job_id: 'j1', workflow: 'earlier' },
        },
      }),
    )

    expect(
      screen.getByRole('link', { name: 'a run of earlier' }),
    ).toHaveAttribute('href', '/runs/j1')
    expect(screen.getByText(/step 1 in a chain/)).toBeInTheDocument()
    expect(screen.queryByRole('note')).toBeNull() // short chain: no warning
  })

  it('warns when runs have been triggering each other for a while', () => {
    renderIt(
      job({
        depth: 4,
        trigger_detail: {
          changes: [],
          caused_by: { job_id: 'j1', workflow: 'compute' },
        },
      }),
    )

    expect(screen.getByRole('note')).toHaveTextContent(
      /Runs are triggering each other/,
    )
    expect(screen.getByRole('note')).toHaveTextContent(/Stop automation/)
  })

  it('does not say a cancelled run failed', () => {
    renderIt(job({ status: 'cancelled' }))
    expect(screen.getByText(/before this run was stopped/)).toBeInTheDocument()
  })

  it('leaves the list of records to its own tab', async () => {
    renderIt(
      job({
        affected_records: [
          { record_id: 'r1', schema_name: 'Selection', action: 'updated' },
        ],
      }),
    )

    expect(screen.queryByText('Records touched')).toBeNull()
    expect(screen.queryByRole('link', { name: /r1|Selection/ })).toBeNull()
    await waitFor(() => expect(labelCalls).toEqual([])) // nothing looked up here
  })
})
