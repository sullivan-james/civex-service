import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ToastProvider } from '../ui'
import { RecordsExplorer, type RecordsExplorerProps } from './RecordsExplorer'
import { HierarchySidebar } from './HierarchySidebar'
import type { CivexRecord } from '../../api/records'
import type { Schema } from '../../api/schemas'
import type { View } from '../../api/views'
import { finishExport } from '../files/testSupport'

// --- a tiny in-memory API: just enough shape to drive the explorer -------

function schema(name: string, parent: Schema | null, fields: string[]): Schema {
  return {
    id: `id-${name}`,
    name,
    label: null,
    description: null,
    parent_id: parent?.id ?? null,
    display_template: null,
    deleted_at: null,
    fields: fields.map((f) => ({
      id: `${name}-${f}`,
      name: f,
      label: null,
      type: 'string',
      required: false,
      restrictions: {},
      default: null,
      position: null,
    })),
  }
}
const encounter = schema('encounter', null, ['site'])
const recording = schema('recording', encounter, ['rate'])
const selection = schema('selection', recording, ['selection_table'])
const SCHEMAS = [encounter, recording, selection]

function record(
  id: string,
  schema_name: string,
  data: Record<string, unknown>,
  child_counts: Record<string, number> = {},
  parent: string | null = null,
): CivexRecord {
  return {
    id,
    dataset_id: 'd',
    schema_name,
    parent_record_id: parent,
    data,
    natural_name: id.toUpperCase(),
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
    reference_labels: null,
    child_counts,
  }
}

const E1 = record('e1', 'encounter', { site: 'Stellwagen' }, { recording: 2 })
const E2 = record('e2', 'encounter', { site: 'Georges' }, { recording: 1 })
const R1 = record('r1', 'recording', { rate: '96' }, { selection: 2 }, 'e1')
const R2 = record('r2', 'recording', { rate: '48' }, { selection: 1 }, 'e1')
const S1 = record('s1', 'selection', { selection_table: 'a.txt' }, {}, 'r1')
const S2 = record('s2', 'selection', { selection_table: 'b.txt' }, {}, 'r1')

const EMPTY_TABLES: View = {
  id: 'v1',
  schema_id: selection.id,
  schema_name: 'selection',
  name: 'Selections missing a table',
  files_layout: 'tree',
  columns: [],
  filter_tree: {
    schema: 'selection',
    field: 'selection_table',
    op: 'is_null',
    value: true,
  },
  sort: [],
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

interface Call {
  method: string
  path: string
  params: URLSearchParams
  body?: Record<string, unknown>
}
let calls: Call[]
// What the selection schema's one saved view is currently called.
let viewName: string
// A test may answer some requests itself before the default API does.
let override: ((url: URL, method: string) => Response | undefined) | null

function page(items: CivexRecord[]) {
  return { items, total: items.length, offset: 0, limit: 50 }
}

function handle(method: string, path: string, p: URLSearchParams) {
  if (path === '/api/schemas') return json(SCHEMAS)
  if (path === '/api/workflows') return json([])
  // The exports saved with the listed kind of record, for the Files menu.
  if (path === '/api/file-access/definitions') return json([])
  if (path.endsWith('/views'))
    return json(
      path.includes('/selection/') ? [{ ...EMPTY_TABLES, name: viewName }] : [],
    )
  if (path === '/api/records/e1') return json({ ...E1, ancestors: [] })
  if (path === '/api/records/r1')
    return json({
      ...R1,
      ancestors: [{ id: 'e1', schema_name: 'encounter', natural_name: 'E1' }],
    })
  if (path.endsWith('/record-counts')) {
    const within = p.get('within')
    if (within === 'e1') return json({ recording: 2, selection: 3 })
    if (within === 'r1') return json({ selection: 2 })
    return json({ encounter: 2, recording: 3, selection: 5 })
  }
  if (path.includes('/views/') && method === 'PATCH') {
    viewName = 'Needs QC'
    return json({ ...EMPTY_TABLES, name: viewName })
  }
  if (path.includes('/views/') && method === 'DELETE')
    return new Response(null, { status: 204 })
  if (method === 'DELETE') return json({ deleted: 1 })
  if (path.endsWith('/records')) {
    const schemaName = p.get('schema')
    const inScope = p.get('within')
    if (p.get('filter'))
      return json(
        page([
          { encounter: E1, recording: R1, selection: S2 }[
            schemaName ?? 'selection'
          ]!,
        ]),
      )
    if (schemaName === 'encounter') return json(page([E1, E2]))
    if (schemaName === 'recording')
      return json(page(inScope === 'e1' ? [R1, R2] : [R1, R2]))
    if (schemaName === 'selection') return json(page([S1, S2]))
  }
  return json(page([]))
}

function Probe() {
  const { search } = useLocation()
  return <output data-testid="search">{search}</output>
}

function renderExplorer(
  props: Partial<RecordsExplorerProps> = {},
  url = '/collections/hb',
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route
              path="*"
              element={
                <>
                  {/* the sidebar pages put beside the explorer */}
                  {('dataset' in props ? props.dataset : 'hb') && (
                    <HierarchySidebar
                      dataset="hb"
                      collectionId="hb"
                      recordId={props.root?.id}
                    />
                  )}
                  <RecordsExplorer dataset="hb" scopeLabel="hb" {...props} />
                  <Probe />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const search = () =>
  new URLSearchParams(screen.getByTestId('search').textContent ?? '')
const recordCalls = () =>
  calls.filter((c) => c.method === 'GET' && c.path.endsWith('/records'))
const lastRecordCall = () => {
  const all = recordCalls()
  return all[all.length - 1]
}

beforeEach(() => {
  calls = []
  viewName = EMPTY_TABLES.name
  override = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: url.pathname,
        params: url.searchParams,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      return (
        override?.(url, method) ??
        handle(method, url.pathname, url.searchParams)
      )
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

async function openNew() {
  await userEvent.click(await screen.findByRole('button', { name: /New/ }))
}
const item = (name: RegExp) => screen.queryByRole('menuitem', { name })

describe('RecordsExplorer', () => {
  describe('an empty collection', () => {
    const emptyCollection = (schemas: string[]) => (url: URL) => {
      if (url.pathname === '/api/collections/hb')
        return json({
          id: 'c1',
          name: 'hb',
          description: null,
          timezone: null,
          record_count: 0,
          deleted_at: null,
          scope: 'local',
          schemas,
        })
      if (url.pathname.endsWith('/record-counts')) return json({})
      return undefined
    }

    it('offers a New entry for each enabled top-level schema', async () => {
      override = emptyCollection(['encounter', 'recording'])
      renderExplorer({}, '/collections/hb')
      await openNew()
      expect(item(/New encounter/)).toBeInTheDocument()
      // a child schema can't start a collection: it needs a parent record
      expect(item(/New recording/)).not.toBeInTheDocument()
    })

    it('says so when no schemas are enabled yet', async () => {
      override = emptyCollection([])
      renderExplorer({}, '/collections/hb')
      expect(await screen.findByText(/has no schemas yet/)).toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: /New/ }),
      ).not.toBeInTheDocument()
    })
  })

  describe('a collection with records at only one level', () => {
    const species = schema('species', null, ['common_name'])
    const withEnabled = (schemas: string[]) => (url: URL) => {
      if (url.pathname === '/api/collections/hb')
        return json({
          id: 'c1',
          name: 'hb',
          description: null,
          timezone: null,
          record_count: 2,
          deleted_at: null,
          scope: 'local',
          schemas,
        })
      if (url.pathname === '/api/schemas') return json([...SCHEMAS, species])
      return undefined
    }

    it('still offers to start a record of any other top-level schema it is for', async () => {
      // records exist at "encounter" only; "species" has none yet, so it has no
      // level of its own, and used to have no way to be created either.
      override = withEnabled(['encounter', 'recording', 'selection', 'species'])
      renderExplorer({}, '/collections/hb')

      await openNew()
      expect(item(/New encounter/)).toBeInTheDocument()
      expect(item(/New species/)).toBeInTheDocument()
      // children need a parent record, so they aren't offered from here
      expect(item(/New recording/)).toBeNull()
    })

    it('does not offer a top-level schema the collection is not for', async () => {
      override = withEnabled(['encounter'])
      renderExplorer({}, '/collections/hb')
      await openNew()
      expect(item(/New encounter/)).toBeInTheDocument()
      expect(item(/New species/)).toBeNull()
    })

    it('offers them only at the top of the collection, not inside a record', async () => {
      override = withEnabled(['encounter', 'recording', 'selection', 'species'])
      renderExplorer({}, '/collections/hb?schema=recording&within=e1')
      await openNew()
      expect(item(/New recording/)).toBeInTheDocument()
      expect(item(/New species/)).toBeNull()
    })

    describe('inside a record', () => {
      const annotation = schema('annotation', recording, ['note'])
      // r2 has no selections yet, so the explorer has nothing to list for it.
      const inside = (url: URL) => {
        if (url.pathname === '/api/records/r2')
          return json({
            ...R2,
            ancestors: [
              { id: 'e1', schema_name: 'encounter', natural_name: 'E1' },
            ],
          })
        if (
          url.pathname.endsWith('/record-counts') &&
          url.searchParams.get('within') === 'r2'
        )
          return json({})
        if (url.pathname === '/api/schemas')
          return json([...SCHEMAS, species, annotation])
        return withEnabled([
          'encounter',
          'recording',
          'selection',
          'species',
          'annotation',
        ])(url)
      }

      it('offers to add what goes in a record that has none yet, under that record', async () => {
        const user = userEvent.setup()
        override = inside
        renderExplorer({ root: { id: 'r2' }, scopeLabel: 'R2' }, '/records/r2')

        await openNew()
        expect(item(/New selection/)).toBeInTheDocument()
        expect(item(/New annotation/)).toBeInTheDocument()
        // not a sibling or a top-level schema, which belong elsewhere
        expect(item(/New recording/)).toBeNull()
        expect(item(/New species/)).toBeNull()
        expect(item(/New encounter/)).toBeNull()

        await user.click(item(/New selection/)!)

        expect(search().get('schema')).toBe('selection')
        expect(search().get('parent')).toBe('r2')
      })

      it('offers every kind of child, not only the kind already listed', async () => {
        override = inside
        renderExplorer({ root: { id: 'r1' }, scopeLabel: 'R1' }, '/records/r1')
        await screen.findByText('a.txt')

        await openNew()
        // the listed kind once (not twice), and the other kind as well
        expect(
          screen.getAllByRole('menuitem', { name: /New selection/ }),
        ).toHaveLength(1)
        expect(item(/New annotation/)).toBeInTheDocument()
      })

      it('does not offer a child schema the collection is not for', async () => {
        override = (url) =>
          url.pathname === '/api/collections/hb'
            ? withEnabled(['encounter', 'recording', 'selection'])(url)
            : inside(url)
        renderExplorer({ root: { id: 'r2' }, scopeLabel: 'R2' }, '/records/r2')

        await openNew()
        expect(item(/New selection/)).toBeInTheDocument()
        expect(item(/New annotation/)).toBeNull()
      })
    })
  })

  it('starts at the top of the hierarchy, not at "all records"', async () => {
    renderExplorer()
    expect(await screen.findByText('Stellwagen')).toBeInTheDocument()
    expect(lastRecordCall().params.get('schema')).toBe('encounter')

    const rail = screen.getByRole('navigation', { name: 'Data hierarchy' })
    expect(within(rail).getByText('Encounter')).toBeInTheDocument()
    expect(within(rail).getByText('Recording')).toBeInTheDocument()
    expect(within(rail).getByText('Selection')).toBeInTheDocument()
    expect(
      within(rail).getByRole('button', { name: /Encounter/ }),
    ).toHaveAttribute('aria-current', 'true')
  })

  it('drills down through rows with the same list, scoped to that record', async () => {
    const user = userEvent.setup()
    renderExplorer()
    await screen.findByText('Stellwagen')

    await user.click(
      screen.getAllByRole('button', { name: '2 recordings →' })[0],
    )
    await screen.findByText('96')

    expect(search().get('schema')).toBe('recording')
    expect(search().get('within')).toBe('e1')
    expect(lastRecordCall().params.get('within')).toBe('e1')

    // ...and once more, to grandchildren of the encounter, by the same means
    await user.click(
      screen.getAllByRole('button', { name: '2 selections →' })[0],
    )
    await screen.findByText('a.txt')
    expect(search().get('schema')).toBe('selection')
    expect(search().get('within')).toBe('r1')
  })

  it('goes back up the trail', async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=selection&within=r1')
    await screen.findByText('a.txt')

    const trail = screen.getByRole('navigation', { name: 'Scope' })
    await user.click(within(trail).getByRole('button', { name: 'E1' }))

    await waitFor(() => expect(search().get('schema')).toBe('recording'))
    expect(search().get('within')).toBe('e1')
  })

  it('jumps level from the rail, dropping a scope that no longer fits', async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=selection&within=r1')
    await screen.findByText('a.txt')

    const rail = screen.getByRole('navigation', { name: 'Data hierarchy' })
    await user.click(within(rail).getByRole('button', { name: /Encounter/ }))

    await waitFor(() => expect(search().get('schema')).toBe('encounter'))
    expect(search().get('within')).toBeNull()
  })

  it("applies a schema's saved filter and sends it, schema-qualified, to the list", async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=selection&within=r1')
    await screen.findByText('a.txt')

    await user.click(
      await screen.findByRole('button', { name: 'Selections missing a table' }),
    )

    await waitFor(() =>
      expect(lastRecordCall().params.get('filter')).toBeTruthy(),
    )
    expect(JSON.parse(lastRecordCall().params.get('filter')!)).toEqual(
      EMPTY_TABLES.filter_tree,
    )
    expect(search().get('view')).toBe('Selections missing a table')
    // shown as a removable chip
    const chip = screen.getByText('Selection Table is empty')
    expect(chip).toBeInTheDocument()

    await user.click(
      screen.getByRole('button', { name: /Remove filter .*is empty/ }),
    )
    await waitFor(() => expect(search().get('filter')).toBeNull())
  })

  it('renames and deletes a saved view in place, names being free text', async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=selection&within=r1')
    await screen.findByText('a.txt')
    await user.click(
      await screen.findByRole('button', { name: 'Selections missing a table' }),
    )
    await user.click(
      screen.getByRole('button', {
        name: 'Manage view Selections missing a table',
      }),
    )
    await user.click(screen.getByRole('menuitem', { name: 'Rename view…' }))
    const dialog = await screen.findByRole('dialog')
    const input = within(dialog).getByRole('textbox')
    await user.clear(input)
    await user.type(input, 'Needs QC (2026)')
    await user.click(within(dialog).getByRole('button', { name: 'Rename' }))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true),
    )
    const patch = calls.find((c) => c.method === 'PATCH')!
    // spaces and punctuation travel URL-encoded
    expect(patch.path).toBe(
      '/api/schemas/selection/views/Selections%20missing%20a%20table',
    )
    await waitFor(() => expect(search().get('view')).toBe('Needs QC'))

    await user.click(
      screen.getByRole('button', { name: 'Manage view Needs QC' }),
    )
    await user.click(screen.getByRole('menuitem', { name: 'Delete view…' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Delete view',
      }),
    )
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE')).toBe(true),
    )
    await waitFor(() => expect(search().get('view')).toBeNull())
  })

  it('keeps the filter as you drill, so the question stays the same', async () => {
    const user = userEvent.setup()
    // "encounters that have a selection with an empty table", then drill in
    const filter = JSON.stringify(EMPTY_TABLES.filter_tree)
    renderExplorer(
      {},
      `/collections/hb?schema=encounter&filter=${encodeURIComponent(filter)}`,
    )
    await screen.findByText('Stellwagen')
    expect(lastRecordCall().params.get('filter')).toBe(filter)

    await user.click(
      screen.getAllByRole('button', { name: '2 recordings →' })[0],
    )
    await waitFor(() => expect(search().get('schema')).toBe('recording'))
    expect(search().get('filter')).toBe(filter)
  })

  it('bulk delete of "all matching" sends the same query the list shows', async () => {
    const user = userEvent.setup()
    // Pretend there are more matches than one page holds.
    const big = { items: [S1, S2], total: 120, offset: 0, limit: 50 }
    override = (url, method) =>
      method === 'GET' && url.pathname.endsWith('/records')
        ? json(big)
        : undefined

    const filter = JSON.stringify(EMPTY_TABLES.filter_tree)
    renderExplorer(
      {},
      `/collections/hb?schema=selection&within=r1&q=a&filter=${encodeURIComponent(filter)}`,
    )
    await screen.findByText('a.txt')

    await user.click(
      screen.getByRole('checkbox', { name: 'Select all records' }),
    )
    await user.click(
      await screen.findByRole('button', { name: 'Select all 120 matching' }),
    )
    await user.click(screen.getByRole('button', { name: 'Delete 120' }))
    const dialog = await screen.findByRole('dialog')
    // over the high-impact threshold: the schema name must be typed
    await user.type(within(dialog).getByRole('textbox'), 'selection')
    await user.click(within(dialog).getByRole('button', { name: 'Delete 120' }))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE')).toBe(true),
    )
    const del = calls.find((c) => c.method === 'DELETE')!
    expect(del.path).toBe('/api/collections/hb/records')
    expect(del.params.get('schema')).toBe('selection')
    expect(del.params.get('within')).toBe('r1')
    expect(del.params.get('search')).toBe('a')
    expect(del.params.get('filter')).toBe(filter)
  })

  describe('running a workflow on the selected records', () => {
    const WORKFLOWS = [
      {
        name: 'contour-stats',
        stem: 'contour-stats',
        record_schema: 'selection',
        inputs: null,
      },
      {
        name: 'any-record',
        stem: 'any-record',
        record_schema: null,
        inputs: null,
      },
      {
        name: 'other-schema',
        stem: 'other-schema',
        record_schema: 'recording',
        inputs: null,
      },
      {
        name: 'import-files',
        stem: 'import-files',
        record_schema: 'selection',
        inputs: { files: { type: 'files' } },
      },
    ]
    let runManyBodies: { name: string; ids: string[] }[]
    beforeEach(() => {
      runManyBodies = []
      override = (url, method) => {
        if (url.pathname === '/api/workflows') return json(WORKFLOWS)
        if (method === 'POST' && url.pathname.endsWith('/run-many')) {
          const name = decodeURIComponent(url.pathname.split('/')[3])
          const body = JSON.parse(
            String(
              (
                fetch as unknown as {
                  mock: { calls: [unknown, RequestInit][] }
                }
              ).mock.calls.slice(-1)[0][1].body,
            ),
          ) as { record_ids: string[] }
          runManyBodies.push({ name, ids: body.record_ids })
          return json({
            started: body.record_ids.map((id) => ({ id: `run-${id}` })),
            skipped: [],
          })
        }
        return undefined
      }
    })

    it('offers only the workflows that fit these records and need nothing per run, and queues one run per ticked record in one request', async () => {
      const user = userEvent.setup()
      renderExplorer({}, '/collections/hb?schema=selection&within=r1')
      await screen.findByText('a.txt')

      // Nothing ticked: no such action.
      expect(
        screen.queryByRole('button', { name: /Run workflow on/ }),
      ).toBeNull()

      await user.click(screen.getAllByRole('checkbox', { name: /^Select / })[1])
      await user.click(screen.getAllByRole('checkbox', { name: /^Select / })[2])
      await user.click(
        screen.getByRole('button', { name: 'Run workflow on 2' }),
      )

      const items = (await screen.findAllByRole('menuitem')).map(
        (i) => i.textContent,
      )
      // for selections or for anything; not another schema's, not one that asks for files
      expect(items).toEqual(['contour-stats', 'any-record'])

      await user.click(screen.getByRole('menuitem', { name: 'contour-stats' }))

      await waitFor(() => expect(runManyBodies).toHaveLength(1)) // one request
      expect(runManyBodies[0].name).toBe('contour-stats')
      expect(runManyBodies[0].ids.sort()).toEqual(['s1', 's2'])
      expect(
        await screen.findByText(/Started contour-stats on 2 records/),
      ).toBeInTheDocument()
      // and the selection is cleared
      expect(
        screen.queryByRole('button', { name: /Run workflow on/ }),
      ).toBeNull()
    })

    it('says plainly which records it could not run on', async () => {
      const user = userEvent.setup()
      const base = override!
      override = (url, method) =>
        method === 'POST' && url.pathname.endsWith('/run-many')
          ? json({
              started: [],
              skipped: [
                { id: 's1', reason: 'No such record.' },
                { id: 's2', reason: 'No such record.' },
              ],
            })
          : base(url, method)
      renderExplorer({}, '/collections/hb?schema=selection&within=r1')
      await screen.findByText('a.txt')
      await user.click(
        screen.getByRole('checkbox', { name: 'Select all records' }),
      )
      await user.click(
        screen.getByRole('button', { name: /Run workflow on 2/ }),
      )
      await user.click(
        await screen.findByRole('menuitem', { name: 'contour-stats' }),
      )

      expect(
        await screen.findByText(
          /Couldn't run contour-stats on 2: No such record\. \(and 1 more\)/,
        ),
      ).toBeInTheDocument()
    })

    it('is not offered when every matching record is selected, only for the ones ticked', async () => {
      const user = userEvent.setup()
      const big = { items: [S1, S2], total: 120, offset: 0, limit: 50 }
      const base = override!
      override = (url, method) =>
        method === 'GET' && url.pathname.endsWith('/records')
          ? json(big)
          : base(url, method)
      renderExplorer({}, '/collections/hb?schema=selection&within=r1')
      await screen.findByText('a.txt')
      await user.click(
        screen.getByRole('checkbox', { name: 'Select all records' }),
      )
      expect(
        screen.getByRole('button', { name: 'Run workflow on 2' }),
      ).toBeInTheDocument()

      await user.click(
        await screen.findByRole('button', { name: 'Select all 120 matching' }),
      )

      expect(
        screen.queryByRole('button', { name: /Run workflow on/ }),
      ).toBeNull()
    })
  })

  it('embedded under a record, lists what is below it; the sidebar keeps the whole tree', async () => {
    renderExplorer({ root: { id: 'e1' }, scopeLabel: 'E1' }, '/records/e1')
    await screen.findByText('96')

    expect(lastRecordCall().params.get('within')).toBe('e1')
    expect(lastRecordCall().params.get('schema')).toBe('recording')
    const rail = screen.getByRole('navigation', { name: 'Data hierarchy' })
    expect(
      within(rail).getByRole('button', { name: /Encounter/ }),
    ).toHaveAttribute('aria-current', 'true')
    expect(within(rail).getByText('Selection')).toBeInTheDocument()
  })

  it('moving up a level sets aside a sort and a bare filter that only fit the level below', async () => {
    const user = userEvent.setup()
    const bare = JSON.stringify({ field: 'selection_table', op: 'is_null' })
    renderExplorer(
      {},
      `/collections/hb?schema=selection&within=r1&sort=selection_table:asc&filter=${encodeURIComponent(bare)}`,
    )
    await screen.findByText('b.txt') // the mock's filtered answer

    const rail = screen.getByRole('navigation', { name: 'Data hierarchy' })
    await user.click(within(rail).getByRole('button', { name: /Recording/ }))
    await waitFor(() =>
      expect(lastRecordCall().params.get('schema')).toBe('recording'),
    )
    expect(lastRecordCall().params.getAll('sort')).toEqual([])
    expect(lastRecordCall().params.get('filter')).toBeNull()
  })

  it('a failed list keeps the filters on screen so they can be fixed', async () => {
    const user = userEvent.setup()
    override = (url) =>
      url.pathname.endsWith('/records') && url.searchParams.get('filter')
        ? new Response(JSON.stringify({ detail: 'Unknown filter field' }), {
            status: 422,
            headers: { 'Content-Type': 'application/json' },
          })
        : undefined
    const f = JSON.stringify({
      schema: 'selection',
      field: 'selection_table',
      op: 'is_null',
      value: true,
    })
    renderExplorer(
      {},
      `/collections/hb?schema=selection&within=r1&filter=${encodeURIComponent(f)}`,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Unknown filter field/,
    )
    // the chip and the search are still there, and clearing recovers
    expect(
      screen.getByRole('button', { name: /Remove filter/ }),
    ).toBeInTheDocument()
    expect(screen.getByRole('searchbox')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(await screen.findByText('a.txt')).toBeInTheDocument()
  })

  it("from a record's page, a sidebar level opens that list within the right record", async () => {
    const user = userEvent.setup()
    renderExplorer({ root: { id: 'r1' }, scopeLabel: 'R1' }, '/records/r1')
    const rail = await screen.findByRole('navigation', {
      name: 'Data hierarchy',
    })
    await user.click(
      await within(rail).findByRole('button', { name: /Selection/ }),
    )
    await waitFor(() => expect(search().get('schema')).toBe('selection'))
    expect(search().get('within')).toBe('r1')

    await user.click(within(rail).getByRole('button', { name: /Encounter/ }))
    await waitFor(() => expect(search().get('schema')).toBe('encounter'))
    expect(search().get('within')).toBeNull()
  })

  it('a schema browsed across collections has no hierarchy and no bulk delete', async () => {
    renderExplorer(
      { dataset: undefined, lockedSchema: 'selection' },
      '/schemas/x/records',
    )
    await screen.findByText('a.txt')
    expect(
      screen.queryByRole('navigation', { name: 'Data hierarchy' }),
    ).toBeNull()
    expect(
      screen.queryByRole('checkbox', { name: 'Select all records' }),
    ).toBeNull()
    expect(calls.some((c) => c.path === '/api/schemas/selection/records')).toBe(
      true,
    )
  })

  describe('choosing columns', () => {
    // A schema with enough fields to have a range of them. Every field starts
    // ticked, so a click on one unticks it.
    const wide = schema('encounter', null, ['site', 'area', 'depth', 'vessel'])

    beforeEach(() => {
      override = (url) =>
        url.pathname === '/api/schemas'
          ? json([wide, recording, selection])
          : undefined
    })

    async function openColumns() {
      const user = userEvent.setup()
      renderExplorer()
      await screen.findByText('Stellwagen')
      await user.click(screen.getByRole('button', { name: /Columns/ }))
      return { user, picker: await screen.findByRole('dialog') }
    }

    const name = (label: string) =>
      within(screen.getByRole('dialog')).getByText(label, { selector: 'label' })
    const cols = () => search().get('cols')

    it('unticks one column with a plain click', async () => {
      const { user } = await openColumns()

      await user.click(name('Vessel'))

      await waitFor(() => expect(cols()).toBe('site,area,depth'))
    })

    it('ticks every column between two with a shift-click', async () => {
      const { user } = await openColumns()
      await user.click(name('Area'))
      await waitFor(() => expect(cols()).toBe('site,depth,vessel'))
      await user.click(name('Depth'))
      await waitFor(() => expect(cols()).toBe('site,vessel'))

      await user.click(name('Area')) // ticks area again: the start of a range
      await waitFor(() => expect(cols()).toContain('area'))
      await user.keyboard('{Shift>}')
      await user.click(name('Depth'))
      await user.keyboard('{/Shift}')

      await waitFor(() => {
        const chosen = (cols() ?? '').split(',')
        expect(chosen).toEqual(
          expect.arrayContaining(['site', 'area', 'depth', 'vessel']),
        )
      })
    })
  })

  describe('the Files menu', () => {
    // Selections hold the files; Encounters and Recordings hold none themselves.
    const holdsFiles = (name: string, parent: Schema | null) => ({
      ...schema(name, parent, []),
      fields: [
        {
          id: `${name}-contour`,
          name: 'contour',
          label: null,
          type: 'file',
          required: false,
          restrictions: {},
          default: null,
          position: null,
        },
      ],
    })
    const FILE_SCHEMAS = [
      encounter,
      recording,
      holdsFiles('selection', recording),
    ]
    const exported = {
      dest: '/p',
      location: 'project',
      linked: 3,
      copied: 0,
      unchanged: 0,
      removed: 0,
      missing: [],
      complete: true,
      opened: true,
    }
    const withFiles = (schemas: Schema[]) => (url: URL) => {
      if (url.pathname === '/api/schemas') return json(schemas)
      if (url.pathname === '/api/store/volumes') return json([])
      if (url.pathname === '/api/file-access/export') return json(exported)
      return undefined
    }
    const filesButton = () => screen.findByRole('button', { name: /^export$/i })

    it('is offered on a list of Encounters, though only what is inside them holds files', async () => {
      override = withFiles(FILE_SCHEMAS)
      renderExplorer()

      expect(await filesButton()).toBeInTheDocument()
    })

    it('takes everything beneath the Encounters listed', async () => {
      override = withFiles(FILE_SCHEMAS)
      renderExplorer()
      await userEvent.click(await filesButton())

      await userEvent.click(screen.getByRole('menuitem', { name: /^export…/i }))
      // It starts as just the table; the files are added from there.
      await userEvent.click(
        screen.getByRole('button', { name: /add files or more tables/i }),
      )
      await userEvent.click(screen.getByRole('checkbox', { name: 'Contour' }))
      await finishExport()

      await waitFor(() =>
        expect(calls.some((c) => c.path === '/api/file-access/export')).toBe(
          true,
        ),
      )
      expect(
        calls.find((c) => c.path === '/api/file-access/export')!.body,
      ).toMatchObject({
        collection: 'hb',
        schema_name: 'encounter',
        below: true,
        mode: 'link',
      })
    })

    it('starts as just the table of what is listed, with a way to add files', async () => {
      override = withFiles(FILE_SCHEMAS)
      renderExplorer()
      await userEvent.click(await filesButton())

      await userEvent.click(screen.getByRole('menuitem', { name: /^export…/i }))

      expect(screen.getByText('The table you’re looking at')).toBeTruthy()
      expect(
        screen.getByRole('button', { name: /add files or more tables/i }),
      ).toBeTruthy()
      // None of the folder choices are in the way.
      expect(screen.queryByText('What goes in the folder')).toBeNull()
    })

    it('exports only the table, without files, unless more is asked for', async () => {
      override = withFiles(FILE_SCHEMAS)
      renderExplorer()
      await userEvent.click(await filesButton())
      await userEvent.click(screen.getByRole('menuitem', { name: /^export…/i }))

      await userEvent.selectOptions(
        screen.getByLabelText('Table format'),
        'xlsx',
      )
      await userEvent.type(screen.getByLabelText('Table file name'), 'Mine')
      // No files: the way to get it is just to download it.
      const dialog = within(screen.getByRole('dialog'))
      await userEvent.click(dialog.getByRole('button', { name: /^next/i }))
      await userEvent.click(dialog.getByRole('button', { name: /^download$/i }))

      await waitFor(() =>
        expect(calls.some((c) => c.path === '/api/file-access/zip')).toBe(true),
      )
      const sent = calls.find((c) => c.path === '/api/file-access/zip')!.body!
      expect(sent).toMatchObject({ files: false })
      expect(sent.tables).toEqual([
        expect.objectContaining({
          format: 'xlsx',
          name: 'Mine',
          kind: 'encounter',
        }),
      ])
    })

    it('adds the files on request, as the full choice of what goes in the folder', async () => {
      override = withFiles(FILE_SCHEMAS)
      renderExplorer()
      await userEvent.click(await filesButton())
      await userEvent.click(screen.getByRole('menuitem', { name: /^export…/i }))

      await userEvent.click(
        screen.getByRole('button', { name: /add files or more tables/i }),
      )

      expect(screen.getByText('What goes in the folder')).toBeTruthy()
      expect(screen.queryByText('The table you’re looking at')).toBeNull()
      // The table is still ticked, and no file is.
      expect(
        (
          screen.getAllByRole('checkbox', {
            name: /^all .* in one table$/i,
          })[0] as HTMLInputElement
        ).checked,
      ).toBe(true)
    })

    it('takes everything beneath the rows ticked, too', async () => {
      override = withFiles(FILE_SCHEMAS)
      renderExplorer()
      await screen.findByText('E1')
      // [0] is "Select all records"; [1] is the first row.
      await userEvent.click(
        screen.getAllByRole('checkbox', { name: /^Select / })[1],
      )
      // The selection bar's own Export is the last one; the top one stays for the table.
      const exports = await screen.findAllByRole('button', {
        name: /^export$/i,
      })
      await userEvent.click(exports[exports.length - 1])

      await userEvent.click(screen.getByRole('menuitem', { name: /^export…/i }))
      await userEvent.click(
        screen.getByRole('button', { name: /add files or more tables/i }),
      )
      await userEvent.click(screen.getByRole('checkbox', { name: 'Contour' }))
      await finishExport()

      await waitFor(() =>
        expect(calls.some((c) => c.path === '/api/file-access/export')).toBe(
          true,
        ),
      )
      const sent = calls.find((c) => c.path === '/api/file-access/export')!.body
      expect(sent).toMatchObject({ below: true })
      expect(sent?.record_ids).toHaveLength(1)
    })

    it('is a table alone where nothing in the tree can hold a file', async () => {
      renderExplorer() // the default schemas have no file fields
      await screen.findByText('E1')

      await userEvent.click(screen.getByRole('button', { name: /^export$/i }))
      await userEvent.click(screen.getByRole('menuitem', { name: /^export…/i }))

      // The rows shown are the table; there are no files to take, so the only
      // thing to add is more tables.
      expect(screen.getByText('The table you’re looking at')).toBeTruthy()
      expect(
        screen.getByRole('button', { name: /^add more tables/i }),
      ).toBeTruthy()
      expect(screen.queryByRole('group', { name: /files$/i })).toBeNull()
    })
  })
})
