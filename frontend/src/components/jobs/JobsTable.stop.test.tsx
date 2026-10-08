import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router'
import type { WorkflowJob } from '../../api/workflows'
import JobsTable from './JobsTable'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const job = (over: Partial<WorkflowJob> = {}): WorkflowJob => ({
  id: 'aaaaaaaa-0000-4000-8000-000000000001',
  workflow_name: 'compute',
  record_id: 'bbbbbbbb-0000-4000-8000-000000000002',
  schema_name: 'Selection',
  trigger: 'record_updated',
  status: 'running',
  error: null,
  error_details: null,
  log: null,
  step_executions: null,
  affected_records: null,
  created_at: '2026-10-04T10:00:00Z',
  started_at: '2026-10-04T10:00:01Z',
  finished_at: null,
  depth: 0,
  trigger_detail: null,
  ...over,
})

let jobs: WorkflowJob[]
let calls: { method: string; path: string }[]
let labelRequests: string[][]
let rerunBodies: string[][]
let skipped: { id: string; reason: string }[]
let jobQueries: URLSearchParams[]
let groups: Record<string, unknown>[]
let recordGroups: Record<string, unknown>[]
let groupQueries: URLSearchParams[]
let rerunPayloads: Record<string, unknown>[]
let deletePayloads: Record<string, unknown>[]
let matchingTotal: number | null

const RUN_FIELDS = [
  ['workflow', 'Workflow', 'string', ['eq', 'ne', 'in', 'is_null']],
  [
    'status',
    'Result',
    'enum',
    ['eq', 'ne', 'in', 'is_null'],
    ['pending', 'running', 'completed', 'failed', 'cancelled'],
  ],
  [
    'error',
    'Error message',
    'string',
    ['eq', 'ne', 'contains', 'in', 'is_null'],
  ],
  ['created_at', 'Queued', 'datetime', ['gt', 'gte', 'lt', 'lte', 'is_null']],
].map(([name, label, type, operators, choices]) => ({
  name,
  label,
  type,
  description: '',
  choices: choices ?? null,
  operators,
}))

beforeEach(() => {
  calls = []
  labelRequests = []
  rerunBodies = []
  skipped = []
  jobQueries = []
  groups = []
  recordGroups = []
  groupQueries = []
  rerunPayloads = []
  deletePayloads = []
  matchingTotal = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      calls.push({ method: init?.method ?? 'GET', path: url.pathname })
      if (url.pathname === '/api/workflows')
        return json([
          { name: 'compute', stem: 'compute' },
          { name: 'follow-up', stem: 'follow-up' },
        ])
      if (url.pathname === '/api/jobs/filter-fields') return json(RUN_FIELDS)
      if (url.pathname === '/api/jobs/failure-groups') {
        groupQueries.push(url.searchParams)
        // The server answers for the runs the filter covers: one record's, or all.
        return json(
          (url.searchParams.get('filter') ?? '').includes('"record"')
            ? recordGroups
            : groups,
        )
      }
      if (url.pathname === '/api/schemas') return json([])
      if (url.pathname === '/api/jobs/rerun') {
        const payload = JSON.parse(String(init?.body)) as {
          ids?: string[]
        }
        rerunPayloads.push(payload)
        const ids = payload.ids ?? ['matched-1', 'matched-2']
        if (payload.ids) rerunBodies.push(ids)
        return json({
          started: ids.map((id) => job({ id: `new-${id.slice(-2)}` })),
          skipped: skipped,
        })
      }
      if (url.pathname === '/api/records/labels') {
        const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
        labelRequests.push(ids)
        return json(
          ids.map((id) => ({
            id,
            schema_name: 'Selection',
            natural_name: `Name of ${id.slice(-1)}`,
            deleted: false,
          })),
        )
      }
      if (url.pathname === '/api/jobs/delete') {
        deletePayloads.push(JSON.parse(String(init?.body)))
        return json({ deleted: 29, kept_unfinished: 1 })
      }
      if (url.pathname === '/api/jobs/count')
        return json({ total: matchingTotal ?? jobs.length })
      if (url.pathname === '/api/jobs') {
        jobQueries.push(url.searchParams)
        return json(jobs)
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Loc() {
  const l = useLocation()
  return <output data-testid="loc">{l.search}</output>
}

function renderIt(recordId?: string, url = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <JobsTable recordId={recordId} />
        <Loc />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Runs table: stopping and what started a run', () => {
  it('can cancel a run that is waiting or running, but not one that finished', async () => {
    jobs = [
      job(),
      job({ id: 'cccccccc-0000-4000-8000-000000000003', status: 'completed' }),
    ]
    const user = userEvent.setup()
    renderIt()

    const cancels = await screen.findAllByRole('button', {
      name: 'Cancel the compute run',
    })
    expect(cancels).toHaveLength(1) // only the running one
    await user.click(cancels[0])

    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === 'POST' &&
            c.path === '/api/jobs/aaaaaaaa-0000-4000-8000-000000000001/cancel',
        ),
      ).toBe(true),
    )
  })

  it('shows the field that started each run, not just that a record was updated', async () => {
    jobs = [
      job({
        status: 'completed',
        trigger_detail: {
          caused_by: null,
          changes: [
            {
              field: 'contour_file',
              before: null,
              after: 'a.csv',
              watched: true,
            },
            { field: 'seed', before: null, after: '2', watched: false },
          ],
        },
      }),
    ]
    renderIt()

    const cell = (await screen.findByText('record_updated')).closest('td')!
    expect(within(cell).getByText('contour_file')).toBeInTheDocument()
    expect(within(cell).queryByText(/seed/)).toBeNull() // only what it watches
  })

  it('shows which workflow started a chained run, and flags a long chain', async () => {
    jobs = [
      job({
        status: 'completed',
        depth: 5,
        trigger_detail: {
          changes: [],
          caused_by: { job_id: 'x', workflow: 'compute' },
        },
      }),
    ]
    renderIt()

    expect(
      await screen.findByText(/by compute · chain of 5/),
    ).toBeInTheDocument()
  })

  it('lists cancelled runs as cancelled', async () => {
    jobs = [job({ status: 'cancelled', finished_at: '2026-10-04T10:00:03Z' })]
    renderIt()
    expect(await screen.findByText('cancelled')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Cancel the/ })).toBeNull()
  })

  it("names each run's record as it is now, for the whole page in one request", async () => {
    const rec = (n: number) => `bbbbbbbb-0000-4000-8000-00000000000${n}`
    jobs = [1, 2, 3, 3].map((n, i) =>
      job({
        id: `aaaaaaaa-0000-4000-8000-00000000010${i}`,
        record_id: rec(n),
        status: 'completed',
      }),
    )
    renderIt()

    expect(
      (await screen.findAllByRole('link', { name: 'Name of 1' }))[0],
    ).toHaveAttribute('href', `/records/${rec(1)}`)
    await waitFor(() =>
      expect(labelRequests.some((r) => r.includes(rec(3)))).toBe(true),
    )
    // Three distinct records across four rows: each asked for once, together.
    // (A request for a record on another page's rows isn't this page's.)
    const mine = labelRequests.filter((r) => r.some((id) => id !== rec(2)))
    expect(mine).toHaveLength(1)
    expect([...mine[0]].sort()).toEqual([rec(1), rec(2), rec(3)])
  })

  it('has few columns: the run is a link, and the time carries the duration', async () => {
    jobs = [job({ status: 'completed', finished_at: '2026-10-04T10:00:03Z' })]
    renderIt()

    await screen.findByRole('link', { name: 'compute' })
    const headers = screen
      .getAllByRole('columnheader')
      .map((h) => h.textContent?.trim())
      .filter(Boolean)
    // Five columns of information, and the row's own actions at the end.
    expect(headers).toEqual([
      'Workflow',
      'Record',
      'Started by',
      'Result',
      'When',
      'Actions',
    ])
    // The whole row opens the run.
    expect(screen.getByRole('link', { name: 'compute' })).toHaveAttribute(
      'href',
      '/runs/aaaaaaaa-0000-4000-8000-000000000001',
    )
  })

  it('filters with the same chips and builder as the records, held in the address', async () => {
    jobs = [job({ status: 'completed' })]
    const filter = {
      and: [
        { field: 'status', op: 'eq', value: 'failed' },
        { field: 'workflow', op: 'eq', value: 'compute' },
      ],
    }
    renderIt(
      undefined,
      `/?filter=${encodeURIComponent(JSON.stringify(filter))}`,
    )

    // each condition is a removable chip, as on the collections page
    expect(
      await screen.findByText(/Result is failed|Result.*failed/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Workflow.*compute/)).toBeInTheDocument()
    await waitFor(() =>
      expect(
        jobQueries.some(
          (q) => JSON.parse(q.get('filter') ?? 'null')?.and?.length === 2,
        ),
      ).toBe(true),
    )
  })

  it('still opens an older link that names a status or workflow directly', async () => {
    jobs = [job({ status: 'failed' })]
    renderIt(undefined, '/?status=failed&workflow=compute')

    await waitFor(() =>
      expect(
        jobQueries.some(
          (q) =>
            JSON.stringify(JSON.parse(q.get('filter') ?? 'null')) ===
            JSON.stringify({
              and: [
                { field: 'workflow', op: 'eq', value: 'compute' },
                { field: 'status', op: 'eq', value: 'failed' },
              ],
            }),
        ),
      ).toBe(true),
    )
  })

  it('removing a chip drops that condition from the request', async () => {
    jobs = [job({ status: 'failed' })]
    const user = userEvent.setup()
    renderIt(
      undefined,
      `/?filter=${encodeURIComponent(JSON.stringify({ field: 'status', op: 'eq', value: 'failed' }))}`,
    )

    await user.click(
      // once the field list has loaded and the chip says "Result …"
      await screen.findByRole('button', { name: /Remove filter Result/ }),
    )

    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: /Remove filter/ }),
      ).toBeNull(),
    )
    await waitFor(() => {
      const last = jobQueries[jobQueries.length - 1]
      expect(last.get('filter')).toBeNull()
    })
  })

  it('shows the real error message, cut to a line, with the step it came from', async () => {
    const long = 'Row 12 has no selection_number. '.repeat(20)
    jobs = [
      job({
        status: 'failed',
        error: long,
        error_details: {
          kind: 'plugin_error',
          message: long,
          retryable: false,
          step: 'import',
        },
      }),
    ]
    renderIt()

    const text = await screen.findByText(
      /^import: Row 12 has no selection_number/,
    )
    // not the generic "unexpected error", and not unbounded
    expect(screen.queryByText(/unexpected error/i)).toBeNull()
    expect((text.textContent ?? '').length).toBeLessThan(170)
    expect(text.textContent).toMatch(/…$/)
    // the whole message is a hover away
    expect(text).toHaveAttribute('title', long)
  })

  it('groups why runs failed, and a group opens just its runs', async () => {
    jobs = [job({ status: 'failed' })]
    groups = [
      {
        workflow: 'compute',
        kind: 'validation_error',
        step: 'import',
        message: 'Missing contour_file',
        count: 31,
        last_at: '2026-10-04T10:00:00Z',
      },
      {
        workflow: 'compute',
        kind: 'timeout',
        step: 'load',
        message: 'took too long',
        count: 2,
        last_at: '2026-10-04T10:00:00Z',
      },
    ]
    const user = userEvent.setup()
    renderIt()

    expect(await screen.findByText('33 failed runs')).toBeInTheDocument()
    await user.click(screen.getByText('33 failed runs'))
    expect(screen.getByText('Missing contour_file')).toBeInTheDocument()
    expect(screen.getByText('took too long')).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Show' })[0])

    await waitFor(() => {
      const last = JSON.parse(
        jobQueries[jobQueries.length - 1].get('filter') ?? 'null',
      )
      expect(last.and).toEqual(
        expect.arrayContaining([
          { field: 'status', op: 'eq', value: 'failed' },
          { field: 'workflow', op: 'eq', value: 'compute' },
          { field: 'error_kind', op: 'eq', value: 'validation_error' },
          { field: 'error', op: 'eq', value: 'Missing contour_file' },
        ]),
      )
    })
  })

  it('keeps the time window when a group is opened, and re-runs a whole group in one request', async () => {
    jobs = [job({ status: 'failed' })]
    groups = [
      {
        workflow: 'compute',
        kind: 'timeout',
        step: 'load',
        message: 'took too long',
        count: 2,
        last_at: '2026-10-04T10:00:00Z',
      },
    ]
    const window = {
      field: 'created_at',
      op: 'gte',
      value: '2026-10-04T09:00:00Z',
    }
    const user = userEvent.setup()
    renderIt(
      undefined,
      `/?filter=${encodeURIComponent(JSON.stringify({ and: [{ field: 'status', op: 'eq', value: 'failed' }, window] }))}`,
    )

    await user.click(await screen.findByRole('button', { name: /Re-run 2$/ }))

    await waitFor(() => expect(rerunPayloads).toHaveLength(1))
    const sent = rerunPayloads[0] as { filter: { and: unknown[] } }
    expect(sent.filter.and).toContainEqual(window) // only this batch's runs
    expect(sent.filter.and).toContainEqual({
      field: 'error_kind',
      op: 'eq',
      value: 'timeout',
    })
    expect(await screen.findByText(/Queued 2 runs/)).toBeInTheDocument()
  })

  it('re-runs every run a filter matches, after asking', async () => {
    jobs = [job({ status: 'failed' })]
    const user = userEvent.setup()
    renderIt(
      undefined,
      `/?filter=${encodeURIComponent(JSON.stringify({ field: 'status', op: 'eq', value: 'failed' }))}`,
    )

    await user.click(
      await screen.findByRole('button', { name: /Re-run all 1…/ }),
    )
    expect(rerunPayloads).toHaveLength(0) // not yet
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/same record with the same input/)
    await user.click(within(dialog).getByRole('button', { name: /^Re-run 1$/ }))

    await waitFor(() => expect(rerunPayloads).toHaveLength(1))
    expect(rerunPayloads[0]).toEqual({
      filter: { field: 'status', op: 'eq', value: 'failed' },
    })
  })

  it('re-runs several selected runs with one request', async () => {
    jobs = [1, 2, 3].map((n) =>
      job({
        id: `aaaaaaaa-0000-4000-8000-0000000000a${n}`,
        status: 'completed',
      }),
    )
    const user = userEvent.setup()
    renderIt()

    const boxes = await screen.findAllByRole('checkbox', {
      name: 'Select the compute run',
    })
    await user.click(boxes[0])
    await user.click(boxes[2])
    expect(
      screen.getByRole('region', { name: 'Bulk actions' }),
    ).toHaveTextContent('2 selected')
    await user.click(screen.getByRole('button', { name: 'Re-run 2' }))

    await waitFor(() => expect(rerunBodies).toHaveLength(1)) // one request, not two
    expect(rerunBodies[0].sort()).toEqual([
      'aaaaaaaa-0000-4000-8000-0000000000a1',
      'aaaaaaaa-0000-4000-8000-0000000000a3',
    ])
    expect(await screen.findByText(/Queued 2 runs/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Bulk actions' })).toBeNull()
  })

  it('selects every run on the page at once, and says what could not be repeated', async () => {
    jobs = [1, 2].map((n) =>
      job({
        id: `aaaaaaaa-0000-4000-8000-0000000000b${n}`,
        status: 'completed',
      }),
    )
    skipped = [{ id: 'x', reason: 'Its record no longer exists.' }]
    const user = userEvent.setup()
    renderIt()

    await user.click(
      await screen.findByRole('checkbox', {
        name: 'Select all runs on this page',
      }),
    )
    expect(
      screen.getByRole('region', { name: 'Bulk actions' }),
    ).toHaveTextContent('2 selected')
    await user.click(screen.getByRole('button', { name: 'Re-run 2' }))

    expect(
      await screen.findByText(/1 couldn't be repeated/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Its record no longer exists/)).toBeInTheDocument()
  })

  it('selects every run that matches, past this page, and deletes them in one request', async () => {
    jobs = [1, 2].map((n) =>
      job({
        id: `aaaaaaaa-0000-4000-8000-0000000000d${n}`,
        status: 'failed',
      }),
    )
    matchingTotal = 30
    const failed = { field: 'status', op: 'eq', value: 'failed' }
    const user = userEvent.setup()
    renderIt(
      undefined,
      `/?filter=${encodeURIComponent(JSON.stringify(failed))}&q=compute`,
    )

    await user.click(
      await screen.findByRole('checkbox', {
        name: 'Select all runs on this page',
      }),
    )
    await user.click(
      screen.getByRole('button', { name: 'Select all 30 matching' }),
    )
    const bar = screen.getByRole('region', { name: 'Bulk actions' })
    expect(bar).toHaveTextContent('All 30 matching selected')
    await user.click(within(bar).getByRole('button', { name: 'Delete 30' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Delete 30',
      }),
    )

    await waitFor(() => expect(deletePayloads).toHaveLength(1))
    // The list's own filter and search, never the ids of one page.
    expect(deletePayloads[0]).toEqual({ filter: failed, search: 'compute' })
    expect(await screen.findByText(/Deleted 29 runs/)).toHaveTextContent(
      '1 still waiting or running was kept',
    )
  })

  it('deletes just the runs ticked on the page', async () => {
    jobs = [1, 2, 3].map((n) =>
      job({
        id: `aaaaaaaa-0000-4000-8000-0000000000e${n}`,
        status: 'failed',
      }),
    )
    const user = userEvent.setup()
    renderIt()

    const boxes = await screen.findAllByRole('checkbox', {
      name: 'Select the compute run',
    })
    await user.click(boxes[0])
    await user.click(boxes[1])
    await user.click(screen.getByRole('button', { name: 'Delete 2' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Delete 2',
      }),
    )

    await waitFor(() => expect(deletePayloads).toHaveLength(1))
    expect(deletePayloads[0]).toEqual({
      ids: [
        'aaaaaaaa-0000-4000-8000-0000000000e1',
        'aaaaaaaa-0000-4000-8000-0000000000e2',
      ],
    })
  })

  it('can clear a selection without doing anything', async () => {
    jobs = [job({ status: 'completed' })]
    const user = userEvent.setup()
    renderIt()

    await user.click(
      (
        await screen.findAllByRole('checkbox', {
          name: 'Select the compute run',
        })
      )[0],
    )
    await user.click(screen.getByRole('button', { name: 'Clear selection' }))

    expect(screen.queryByRole('region', { name: 'Bulk actions' })).toBeNull()
    expect(rerunBodies).toEqual([])
  })

  it('selects a run of rows with shift-click', async () => {
    jobs = [1, 2, 3, 4, 5].map((n) =>
      job({
        id: `aaaaaaaa-0000-4000-8000-0000000000c${n}`,
        status: 'completed',
      }),
    )
    const user = userEvent.setup()
    renderIt()

    const boxes = await screen.findAllByRole('checkbox', {
      name: 'Select the compute run',
    })
    await user.click(boxes[1])
    await user.keyboard('{Shift>}')
    await user.click(boxes[3])
    await user.keyboard('{/Shift}')

    expect(
      screen.getByRole('region', { name: 'Bulk actions' }),
    ).toHaveTextContent('3 selected')
    expect(boxes.map((b) => (b as HTMLInputElement).checked)).toEqual([
      false,
      true,
      true,
      true,
      false,
    ])
  })

  it('opens a run with the record remembered when listed on that record, so its breadcrumb can lead back', async () => {
    jobs = [job({ status: 'completed' })]
    renderIt('rec-123')

    const link = await screen.findByRole('link', { name: 'compute' })
    expect(link).toHaveAttribute(
      'href',
      '/runs/aaaaaaaa-0000-4000-8000-000000000001?from=rec-123',
    )
  })

  it('opens a run plainly when listed on the Runs page', async () => {
    jobs = [job({ status: 'completed' })]
    renderIt()

    expect(
      await screen.findByRole('link', { name: 'compute' }),
    ).toHaveAttribute('href', '/runs/aaaaaaaa-0000-4000-8000-000000000001')
  })

  it('does not show a run that left things undone as a plain success', async () => {
    jobs = [
      job({
        status: 'completed',
        finished_at: '2026-10-04T10:00:03Z',
        step_executions: [
          {
            step_id: 'import',
            plugin: 'civex.match_files_to_records',
            status: 'success',
            inputs: {},
            outputs: {
              created: 2,
              updated: 0,
              unmatched: ['nope.csv'],
              ambiguous: ['a_sel_14.csv (key 14 is also in: b_sel_149.csv)'],
            },
            duration_seconds: 1,
            error: null,
            depends_on: [],
          },
        ],
      }),
      job({
        id: 'cccccccc-0000-4000-8000-000000000009',
        status: 'completed',
        finished_at: '2026-10-04T10:00:03Z',
      }),
    ]
    renderIt()

    expect(
      await screen.findByText('completed with 2 problems'),
    ).toBeInTheDocument()
    // the clean one still says plainly that it completed
    expect(
      screen.getAllByText('completed').some((el) => el.closest('td')),
    ).toBe(true)
  })
})

const RECORD = 'bbbbbbbb-0000-4000-8000-000000000002'
const FAILURES = [
  {
    workflow: 'compute',
    kind: 'timeout',
    step: 'load',
    message: 'took too long',
    count: 448,
    last_at: '2026-10-04T10:00:00Z',
  },
]
const recordScope = { field: 'record', op: 'eq', value: RECORD }

describe("Runs table on a record: counts and bulk actions are that record's", () => {
  it("asks for the failures of this record's runs, not of every run", async () => {
    jobs = []
    groups = FAILURES // the whole project's failures
    recordGroups = []
    renderIt(RECORD)

    await waitFor(() => expect(groupQueries.length).toBeGreaterThan(0))
    for (const q of groupQueries)
      expect(JSON.parse(q.get('filter')!)).toEqual(recordScope)
    expect(screen.queryByText(/failed runs?$/)).toBeNull()
  })

  it("does not show the Runs page's failures after visiting it", async () => {
    // The same cache serves both pages, as in the app.
    jobs = []
    groups = FAILURES
    recordGroups = []
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const page = (recordId?: string) => (
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <JobsTable recordId={recordId} />
        </MemoryRouter>
      </QueryClientProvider>
    )
    const first = render(page())
    expect(await screen.findByText('448 failed runs')).toBeInTheDocument()
    first.unmount()

    render(page(RECORD))
    await waitFor(() =>
      expect(
        groupQueries.some((q) => (q.get('filter') ?? '').includes('"record"')),
      ).toBe(true),
    )
    expect(screen.queryByText('448 failed runs')).toBeNull()
  })

  it("shows this record's own failures, and counts only them", async () => {
    jobs = [job({ status: 'failed' })]
    recordGroups = [{ ...FAILURES[0], count: 3 }]
    renderIt(RECORD)
    expect(await screen.findByText('3 failed runs')).toBeInTheDocument()
  })

  it("re-running a failure group on a record re-runs this record's runs only", async () => {
    jobs = [job({ status: 'failed' })]
    recordGroups = [{ ...FAILURES[0], count: 3 }]
    const user = userEvent.setup()
    renderIt(RECORD)

    await user.click(await screen.findByText('3 failed runs')) // open the groups
    await user.click(await screen.findByRole('button', { name: /Re-run 3$/ }))
    await waitFor(() => expect(rerunPayloads).toHaveLength(1))
    const sent = rerunPayloads[0] as { filter: { and: unknown[] } }
    expect(sent.filter.and).toContainEqual(recordScope)
    expect(sent.filter.and).toContainEqual({
      field: 'error_kind',
      op: 'eq',
      value: 'timeout',
    })
  })

  it('re-running everything a filter matches stays on this record', async () => {
    jobs = [job({ status: 'failed' })]
    const user = userEvent.setup()
    renderIt(
      RECORD,
      `/?filter=${encodeURIComponent(JSON.stringify({ field: 'status', op: 'eq', value: 'failed' }))}`,
    )
    await user.click(
      await screen.findByRole('button', { name: /Re-run all 1…/ }),
    )
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^Re-run 1$/ }))

    await waitFor(() => expect(rerunPayloads).toHaveLength(1))
    expect(rerunPayloads[0]).toEqual({
      filter: {
        and: [recordScope, { field: 'status', op: 'eq', value: 'failed' }],
      },
    })
  })

  it('does not add a record scope on the Runs page itself', async () => {
    jobs = [job({ status: 'failed' })]
    groups = FAILURES
    renderIt()
    await screen.findByText('448 failed runs')
    for (const q of groupQueries) expect(q.get('filter')).toBeNull()
  })
})
