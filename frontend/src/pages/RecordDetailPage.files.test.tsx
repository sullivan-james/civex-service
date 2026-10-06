import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui/ToastProvider'
import RecordDetailPage from './RecordDetailPage'
import { finishExport } from '../components/files/testSupport'

afterEach(() => vi.unstubAllGlobals())

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

const field = (name: string, type: string) => ({
  id: name,
  name,
  label: null,
  type,
  required: false,
  restrictions: {},
  default: null,
  position: null,
})
const schema = (
  id: string,
  parent: string | null,
  fields: [string, string][],
) => ({
  id,
  name: id,
  label: null,
  description: null,
  parent_id: parent,
  display_template: null,
  fields: fields.map(([n, t]) => field(n, t)),
  deleted_at: null,
})

// Encounter -> Recording -> Selection: the files are on the Selections.
const FILES_BELOW = [
  schema('encounter', null, [['site', 'string']]),
  schema('recording', 'encounter', [['rate', 'integer']]),
  schema('selection', 'recording', [['table', 'file']]),
]
const NO_FILES = [
  schema('encounter', null, [['site', 'string']]),
  schema('recording', 'encounter', [['rate', 'integer']]),
]

const record = (schemaName: string, id: string) => ({
  id,
  dataset_id: 'c1',
  schema_name: schemaName,
  parent_record_id: null,
  data: { site: 'Stellwagen' },
  natural_name: 'Encounter 7',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  deleted_at: null,
  reference_labels: null,
  ancestors: [],
})

function renderPage(
  schemas: unknown[],
  schemaName = 'encounter',
  presets: unknown[] = [],
) {
  const requests: { path: string; body: Record<string, unknown> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://x').pathname
      requests.push({ path, body: JSON.parse(String(init?.body ?? '{}')) })
      if (path === '/api/records/e7') return json(record(schemaName, 'e7'))
      if (path === '/api/collections/c1')
        return json({ id: 'c1', name: 'hb', timezone: null, scope: 'local' })
      if (path === '/api/schemas') return json(schemas)
      if (path === '/api/store/volumes') return json([])
      if (path.endsWith('/record-counts')) return json({})
      if (path === '/api/workflows' || path === '/api/jobs') return json([])
      if (path === '/api/file-access/definitions') return json(presets)
      if (path === '/api/file-access/export')
        return json({
          dest: '/p',
          location: 'project',
          linked: 2,
          copied: 0,
          unchanged: 0,
          removed: 0,
          missing: [],
          complete: true,
          opened: true,
        })
      return json({})
    }),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/records/e7']}>
          <Routes>
            <Route path="/records/:id" element={<RecordDetailPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return requests
}

describe('files on a record page', () => {
  it('offers an Encounter its files, though only its Selections hold any', async () => {
    renderPage(FILES_BELOW)

    expect(
      await screen.findByRole('button', { name: /^export$/i }),
    ).toBeTruthy()
  })

  it('opens every file under the record, named from the record', async () => {
    const requests = renderPage(FILES_BELOW)
    await userEvent.click(
      await screen.findByRole('button', { name: /^export$/i }),
    )

    await userEvent.click(screen.getByRole('menuitem', { name: /^export…/i }))
    await finishExport()

    const sent = await vi.waitFor(() => {
      const r = requests.find((q) => q.path === '/api/file-access/export')
      if (!r) throw new Error('not sent yet')
      return r
    })
    // The record, and everything beneath it, whatever schema: no `schema_name`.
    expect(sent.body).toMatchObject({
      within: 'e7',
      name: 'Encounter 7',
      mode: 'link',
    })
    expect(sent.body.schema_name).toBeUndefined()
  })

  it('offers the exports saved with this kind of record, and where to set more up', async () => {
    const requests = renderPage(FILES_BELOW, 'encounter', [
      {
        id: 'd1',
        schema_id: 'encounter',
        schema_name: 'encounter',
        name: 'Contours',
        holder: 'selection',
        fields: ['contour'],
        filter_tree: null,
        files_layout: 'flat',
        include_files: true,
        tables: [],
      },
    ])
    await userEvent.click(
      await screen.findByRole('button', { name: /^export$/i }),
    )

    expect(
      screen.getByRole('menuitem', {
        name: /contours.*contour of selection · all in one folder/i,
      }),
    ).toBeTruthy()
    expect(
      screen.getByRole('menuitem', { name: /set up exports/i }),
    ).toBeTruthy()
    await userEvent.click(screen.getByRole('menuitem', { name: /contours/i }))
    await finishExport('folder', 0)

    const sent = await vi.waitFor(() => {
      const r = requests.find((q) => q.path === '/api/file-access/export')
      if (!r) throw new Error('not sent yet')
      return r
    })
    // The export saved with Encounters, run on this Encounter.
    expect(sent.body).toMatchObject({
      export: 'encounter/Contours',
      within: 'e7',
      name: 'Encounter 7-Contours',
    })
  })

  it('stays out of the way where nothing beneath can hold a file', async () => {
    renderPage(NO_FILES)

    // The page has loaded once the record's own heading is there.
    await screen.findByRole('heading', { name: /encounter 7/i })

    expect(screen.queryByRole('button', { name: /^export$/i })).toBeNull()
  })
})
