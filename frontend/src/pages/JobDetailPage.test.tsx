import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import JobDetailPage from './JobDetailPage'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const RUN = '649f5bde-c669-4182-b3ae-40670e0d0c8c'
const ORIGIN = 'cfedda82-d73d-41c0-8913-7c26cbfa1595'

const run = {
  id: RUN,
  workflow_name: 'Import contours',
  record_id: ORIGIN,
  schema_name: 'Recording',
  trigger: 'manual',
  status: 'completed',
  error: null,
  error_details: null,
  log: null,
  step_executions: [
    {
      step_id: 'import',
      plugin: 'civex.match_files_to_records',
      status: 'success',
      inputs: {},
      outputs: {
        created: 2,
        updated: 0,
        unmatched: [],
        ambiguous: [],
      } as Record<string, unknown>,
      duration_seconds: 1,
      error: null,
      depends_on: [],
    },
  ],
  affected_records: [
    { record_id: 's1', schema_name: 'Selection', action: 'created' },
    { record_id: 's2', schema_name: 'Selection', action: 'created' },
  ],
  created_at: '2026-10-04T15:43:13Z',
  started_at: '2026-10-04T15:43:13Z',
  finished_at: '2026-10-04T15:43:14Z',
  depth: 0,
  trigger_detail: null,
}

const origin = {
  id: ORIGIN,
  dataset_id: 'd1',
  schema_name: 'Recording',
  parent_record_id: 'enc1',
  data: {},
  natural_name: 'Recording 1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  deleted_at: null,
  reference_labels: null,
  ancestors: [
    { id: 'enc1', schema_name: 'Encounter', natural_name: 'Encounter A' },
  ],
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const p = url.pathname
      if (p === `/api/jobs/${RUN}`) return json(run)
      if (p === `/api/records/${ORIGIN}`) return json(origin)
      if (p === '/api/collections/d1')
        return json({
          id: 'd1',
          name: 'Test Datas',
          record_count: 3,
          timezone: null,
        })
      if (p === '/api/workflows')
        return json([{ name: 'Import contours', stem: 'import_contours' }])
      if (p === '/api/plugins') return json([])
      if (p === '/api/records/labels') {
        const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
        return json(
          ids.map((id) => ({
            id,
            schema_name: 'Selection',
            natural_name: `Name of ${id}`,
            deleted: false,
          })),
        )
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const { pathname, search } = useLocation()
  return <output data-testid="where">{pathname + search}</output>
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/runs/:id" element={<JobDetailPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const crumbs = () =>
  within(screen.getByRole('navigation', { name: /breadcrumb/i }))

describe('a run’s page', () => {
  it('opened from the Runs list, sits under Runs', async () => {
    renderAt(`/runs/${RUN}`)

    await screen.findByRole('heading', { name: 'Import contours' })
    expect(crumbs().getByRole('link', { name: 'Runs' })).toHaveAttribute(
      'href',
      '/runs',
    )
    expect(crumbs().queryByText('Recording 1')).toBeNull()
  })

  it('opened from a record, has a breadcrumb up to that recording, ending on its Runs tab', async () => {
    renderAt(`/runs/${RUN}?from=${ORIGIN}`)

    // Collections › the collection › each record down to the one it came from.
    await crumbs().findByRole('link', { name: 'Test Datas' })
    const links = crumbs().getAllByRole('link')
    expect(links.map((a) => a.textContent)).toEqual([
      'Collections',
      'Test Datas',
      expect.stringContaining('Encounter A'),
      expect.stringContaining('Recording 1'),
    ])
    expect(links[1]).toHaveAttribute('href', '/collections/d1')
    expect(links[2]).toHaveAttribute('href', '/records/enc1')
    // The record it came from: back to where the run was opened, its Runs tab.
    expect(links[3]).toHaveAttribute('href', `/records/${ORIGIN}?tab=runs`)
    // And the run itself is the last, current, crumb.
    expect(crumbs().getByText(/Run 649f5bde/)).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('has the browser tab name the run and where it is', async () => {
    renderAt(`/runs/${RUN}?from=${ORIGIN}`)
    await crumbs().findByRole('link', { name: /Recording 1/ })

    await waitFor(() =>
      expect(document.title).toBe(
        'Import contours · Recording 1 · Encounter A · civex',
      ),
    )
  })

  it('shows the summary first, with the records in a tab of their own', async () => {
    const user = userEvent.setup()
    renderAt(`/runs/${RUN}`)

    await screen.findByRole('tab', { name: 'Records touched (2)' })
    expect(screen.getByRole('tab', { name: 'Summary' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    // Not on the summary...
    expect(screen.queryByRole('link', { name: 'Name of s1' })).toBeNull()

    await user.click(screen.getByRole('tab', { name: 'Records touched (2)' }))

    // ...but here, named as they are now.
    expect(
      await screen.findByRole('link', { name: 'Name of s1' }),
    ).toHaveAttribute('href', '/records/s1')
    expect(screen.getByRole('link', { name: 'Name of s2' })).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('tab=records')
  })

  it('keeps the tab in the address, and keeps where it came from when changing tab', async () => {
    const user = userEvent.setup()
    renderAt(`/runs/${RUN}?from=${ORIGIN}`)

    await user.click(await screen.findByRole('tab', { name: 'Steps' }))

    const where = screen.getByTestId('where').textContent ?? ''
    expect(where).toContain('tab=steps')
    expect(where).toContain(`from=${ORIGIN}`)
  })

  it('puts the steps in their own tab too', async () => {
    const user = userEvent.setup()
    renderAt(`/runs/${RUN}?tab=steps`)

    expect(await screen.findByRole('tab', { name: 'Steps' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(
      await screen.findByText(/match_files_to_records|Match Files/i),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Summary' }))
    expect(screen.queryByText(/match_files_to_records/)).toBeNull()
  })

  it('links to its workflow', async () => {
    renderAt(`/runs/${RUN}`)

    const link = await screen.findByRole('link', { name: 'Import contours' })
    expect(link).toHaveAttribute('href', '/workflows/import_contours/edit')
  })

  it('says up front what a completed run still got wrong, and names the files', async () => {
    run.step_executions[0].outputs = {
      created: 2,
      updated: 0,
      unmatched: ['nope.csv'],
      ambiguous: ['a_sel_14.csv (key 14 is also in: b_sel_149.csv)'],
    }
    renderAt(`/runs/${RUN}`)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('finished, but not everything worked')
    expect(alert).toHaveTextContent('1 file matched no record')
    expect(alert).toHaveTextContent(
      'left alone because another file has the same key',
    )
    expect(alert).toHaveTextContent('nope.csv')
    expect(alert).toHaveTextContent('b_sel_149.csv')
    expect(screen.getByText('completed with 2 problems')).toBeInTheDocument()
  })

  it('shows no warning for a run that did everything', async () => {
    run.step_executions[0].outputs = {
      created: 2,
      updated: 0,
      unmatched: [],
      ambiguous: [],
    }
    renderAt(`/runs/${RUN}`)

    await screen.findByRole('heading', { name: 'Import contours' })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText('completed')).toBeInTheDocument()
  })
})
