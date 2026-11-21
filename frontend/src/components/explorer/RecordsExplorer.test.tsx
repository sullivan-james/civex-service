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
import { setFieldTypesForTest } from '../../hooks/useFieldTypes'

// The map itself (OpenLayers) is not drawn here: a stand-in lists what it got.
vi.mock('../geo/RecordsMap', () => ({
  default: ({ points }: { points: { name: string | null }[] }) => (
    <ul aria-label="map">
      {points.map((p) => (
        <li key={p.name}>{p.name}</li>
      ))}
    </ul>
  ),
}))

// A chart's container measures its parent, which has no size here: draw at a
// fixed size instead.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  const { cloneElement } = await import('react')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactElement }) =>
      cloneElement(
        children as React.ReactElement<{ width: number; height: number }>,
        {
          width: 600,
          height: 300,
        },
      ),
  }
})

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
  if (path === '/api/file-access/files')
    return json({ total: 0, summary: [], items: [] })
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
  await userEvent.click(await screen.findByRole('button', { name: /^New$/ }))
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

    it('offers a New entry for each top-level schema', async () => {
      override = emptyCollection([])
      renderExplorer({}, '/collections/hb')
      await openNew()
      expect(item(/New encounter/)).toBeInTheDocument()
      // a child schema can't start a collection: it needs a parent record
      expect(item(/New recording/)).not.toBeInTheDocument()
    })

    it('guides to a schema first, apart from New, when there are none', async () => {
      override = (url) => {
        if (url.pathname === '/api/schemas') return json([])
        return emptyCollection([])(url)
      }
      renderExplorer({}, '/collections/hb')
      expect(await screen.findByText('Nothing here yet')).toBeInTheDocument()
      expect(screen.getByText(/No schema yet/)).toBeInTheDocument()
      const link = screen.getByRole('link', { name: 'New schema…' })
      expect(link).toHaveAttribute('href', '/schemas?new=1')
      // records come second: no New menu until there is a schema
      expect(
        screen.queryByRole('button', { name: /^New/ }),
      ).not.toBeInTheDocument()
    })

    it('says which schemas are here and offers New for records', async () => {
      override = emptyCollection(['encounter'])
      renderExplorer({}, '/collections/hb')
      expect(
        await screen.findByText(/You have Encounter\./),
      ).toBeInTheDocument()
      await openNew()
      expect(item(/New encounter/)).toBeInTheDocument()
      expect(item(/New schema/)).toBeNull()
    })

    it('switches New schema… off, saying why, for someone who may not change the structure', async () => {
      override = (url) => {
        if (url.pathname === '/api/schemas') return json([])
        if (url.pathname === '/api/me')
          return json({
            account: null,
            permissions: {
              actions: { read: ['project'], write_records: ['project'] },
              all: {},
            },
          })
        return emptyCollection([])(url)
      }
      renderExplorer({}, '/collections/hb')
      expect(await screen.findByText('Nothing here yet')).toBeInTheDocument()
      const button = await screen.findByRole('button', { name: 'New schema…' })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title')
    })
  })

  describe('inside a record', () => {
    it('the rail offers a schema that goes inside this one, apart from New', async () => {
      renderExplorer({ root: { id: 'e1' } }, '/records/e1?tab=contains')
      await openNew()
      expect(item(/New schema/)).toBeNull()
      const link = await screen.findByRole('link', { name: 'New schema…' })
      expect(link).toHaveAttribute('href', '/schemas?new=1&parent=encounter')
    })
  })

  describe('a collection with records at only one level', () => {
    const species = schema('species', null, ['common_name'])
    const withSpecies = (url: URL) => {
      if (url.pathname === '/api/collections/hb')
        return json({
          id: 'c1',
          name: 'hb',
          description: null,
          timezone: null,
          record_count: 2,
          deleted_at: null,
          scope: 'local',
        })
      if (url.pathname === '/api/schemas') return json([...SCHEMAS, species])
      return undefined
    }

    it('still offers to start a record of any other top-level schema it is for', async () => {
      // records exist at "encounter" only; "species" has none yet, so it has no
      // level of its own, and used to have no way to be created either.
      override = withSpecies
      renderExplorer({}, '/collections/hb')

      await openNew()
      expect(item(/New encounter/)).toBeInTheDocument()
      expect(item(/New species/)).toBeInTheDocument()
      // children need a parent record, so they aren't offered from here
      expect(item(/New recording/)).toBeNull()
    })

    it('offers them only at the top of the collection, not inside a record', async () => {
      override = withSpecies
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
        return withSpecies(url)
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
      await screen.findByRole('button', {
        name: /^Selections missing a table/,
      }),
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
      await screen.findByRole('button', {
        name: /^Selections missing a table/,
      }),
    )
    await user.click(
      screen.getByRole('button', {
        name: 'Manage saved filter Selections missing a table',
      }),
    )
    await user.click(screen.getByRole('menuitem', { name: 'Rename…' }))
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
      screen.getByRole('button', { name: 'Manage saved filter Needs QC' }),
    )
    await user.click(screen.getByRole('menuitem', { name: 'Delete…' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Delete',
      }),
    )
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE')).toBe(true),
    )
    await waitFor(() => expect(search().get('view')).toBeNull())
  })

  it('lists records with open notes with what is open, each opening on its notes', async () => {
    const filter = JSON.stringify({
      field: '@open_notes',
      op: 'eq',
      value: true,
    })
    override = (url) =>
      url.pathname.endsWith('/records') && url.searchParams.get('filter')
        ? json(page([{ ...E1, open_notes: 2, latest_note: 'depth looks off' }]))
        : undefined
    renderExplorer(
      {},
      `/collections/hb?schema=encounter&filter=${encodeURIComponent(filter)}`,
    )
    expect(
      await screen.findByText('2 open · depth looks off'),
    ).toBeInTheDocument()
    expect(lastRecordCall().params.get('filter')).toBe(filter)
    expect(
      screen
        .getAllByRole('link')
        .some((a) => a.getAttribute('href') === '/records/e1?tab=notes'),
    ).toBe(true)
  })

  it('lists every kind at once, with what every record has', async () => {
    const user = userEvent.setup()
    override = (url) =>
      url.pathname === '/api/collections/hb/records' &&
      !url.searchParams.get('schema')
        ? json(
            page([
              { ...E1, collection: 'hb' },
              { ...R1, collection: 'hb' },
              { ...S1, collection: 'hb' },
            ]),
          )
        : undefined
    renderExplorer({}, '/collections/hb?schema=*')
    expect(await screen.findByText('E1')).toBeInTheDocument()
    expect(lastRecordCall().params.get('schema')).toBeNull()
    for (const kind of ['Encounter', 'Recording', 'Selection'])
      expect(
        within(screen.getByRole('table')).getByText(kind),
      ).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: /Last edited/ }),
    ).toBeInTheDocument()
    // The kind list offers All kinds, and it is the one picked.
    expect(screen.getByRole('button', { name: 'All kinds' })).toHaveAttribute(
      'aria-current',
      'true',
    )
    // The charts column counts each kind; a bar lists that kind.
    expect(
      within(screen.getByRole('region', { name: 'Charts' })).getByText(
        'How many of each kind',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Choose columns' })).toBeNull()
    await user.click(screen.getByRole('checkbox', { name: /Select record E1/ }))
    expect(screen.getByRole('button', { name: 'Edit…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Run workflow' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move to…' })).toBeEnabled()
    // Picking a kind lists that kind as before.
    await user.click(screen.getAllByRole('button', { name: /^Recording/ })[0])
    await waitFor(() => expect(search().get('schema')).toBe('recording'))
  })

  it('finds open notes on any kind from All records', async () => {
    const filter = JSON.stringify({
      field: '@open_notes',
      op: 'eq',
      value: true,
    })
    override = (url) =>
      url.pathname === '/api/records/all'
        ? json(
            page([
              {
                ...S1,
                collection: 'hb',
                open_notes: 1,
                latest_note: 'wrong table',
              },
            ]),
          )
        : undefined
    renderExplorer(
      { dataset: undefined },
      `/collections?tab=records&filter=${encodeURIComponent(filter)}`,
    )
    expect(await screen.findByText('1 open · wrong table')).toBeInTheDocument()
    const sent = calls.filter((c) => c.path === '/api/records/all').pop()!
    expect(sent.params.get('schema')).toBeNull()
    expect(sent.params.get('filter')).toBe(filter)
    expect(
      screen
        .getAllByRole('link')
        .some((a) => a.getAttribute('href') === '/records/s1?tab=notes'),
    ).toBe(true)
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
      expect(screen.queryByText('What to include')).toBeNull()
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

      expect(screen.getByText('What to include')).toBeTruthy()
      expect(screen.queryByText('The table you’re looking at')).toBeNull()
      // The table is still ticked, and no file is.
      expect(
        (
          screen.getAllByRole('checkbox', {
            name: /^one spreadsheet of all /i,
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

  it('shows the files of exactly the records it lists, under the same filter', async () => {
    const filter = JSON.stringify({
      and: [
        {
          schema: 'selection',
          field: 'selection_table',
          op: 'eq',
          value: 'a.txt',
        },
      ],
    })
    // Reached from the page's menu (`show=files`), not a switch beside the
    // records.
    renderExplorer(
      {},
      `/collections/hb?schema=recording&show=files&filter=${encodeURIComponent(filter)}`,
    )
    expect(screen.queryByRole('radio', { name: /files/i })).toBeNull()
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/file-access/files')?.body,
      ).toMatchObject({
        collection: 'hb',
        schema_name: 'recording',
        filter: JSON.parse(filter),
        below: true,
      }),
    )
    expect(search().get('filter')).toBe(filter) // one filter for both
    // The charts count records, so they step aside; one click goes back.
    expect(screen.queryByRole('region', { name: 'Charts' })).toBeNull()
    await userEvent.click(
      screen.getByRole('button', { name: 'Back to records' }),
    )
    await waitFor(() => expect(search().get('show')).toBeNull())
    expect(search().get('filter')).toBe(filter)
  })
})

describe('charts beside the records', () => {
  const types = {
    types: [
      {
        type: 'string',
        label: 'Text',
        description: '',
        stored_as: '',
        entry_hint: '',
        example: '',
        restrictions: [],
        supports_default: true,
        searchable: true,
        measures: ['filled', 'distinct', 'min', 'max'],
        grouping: 'value' as const,
        buckets: [],
      },
      {
        type: 'geo',
        label: 'Location',
        description: '',
        stored_as: '',
        entry_hint: '',
        example: '',
        restrictions: [],
        supports_default: false,
        searchable: false,
        measures: ['filled'],
        grouping: null,
        buckets: [],
      },
    ],
    kinds: [],
    summary_measures: [],
  }
  const site = (value: string) => ({
    field: 'site',
    schema: 'encounter',
    op: 'eq',
    value,
  })
  const bySite = { id: 'a', group_by: ['encounter.site'], measures: ['count'] }
  const byRate = { id: 'b', group_by: ['rate'], measures: ['count'] }
  // What the kind opens with; a test may change it before rendering.
  let kindCharts: unknown[]
  let put: unknown[] | null
  let me: unknown

  const column = (key: string, field: string, schema_name: string) => ({
    key,
    field,
    schema_name,
    label: field,
    type: 'string',
    bucket: null,
    bin: null,
    unit: null,
  })
  const group = (value: string, n: number, where: unknown) => ({
    groups: [
      { value, label: value, lower: null, upper: null, precision: null },
    ],
    values: [n],
    where,
  })
  const count = {
    key: 'count',
    measure: 'count',
    label: 'Records',
    field: null,
    schema_name: null,
    type: null,
    unit: null,
  }
  /** The summaries asked for, by what they group by. */
  const last = <T,>(list: T[]) => list[list.length - 1]
  const asked = (by: string) =>
    calls.filter(
      (c) =>
        c.path === '/api/records/summary' &&
        JSON.stringify(c.body?.group_by) === JSON.stringify([by]),
    )

  beforeEach(() => {
    setFieldTypesForTest(types)
    kindCharts = [bySite, byRate]
    put = null
    me = undefined
    override = (url: URL, method: string) => {
      if (url.pathname === '/api/schemas')
        return json([
          encounter,
          { ...recording, charts: kindCharts },
          selection,
        ])
      if (
        url.pathname === '/api/schemas/recording/charts' &&
        method === 'PUT'
      ) {
        put = calls[calls.length - 1].body!.charts as unknown[]
        return json({ ...recording, charts: put })
      }
      if (url.pathname === '/api/me')
        return me ? json(me) : new Response(null, { status: 404 })
      if (url.pathname === '/api/records/summary' && method === 'POST') {
        const body = calls[calls.length - 1].body!
        const by = (body.group_by as string[])[0]
        if (by === 'rate')
          return json({
            schema_name: 'recording',
            group_columns: [column('rate', 'rate', 'recording')],
            measure_columns: [count],
            rows: [
              group('48', 1, {
                field: 'rate',
                schema: 'recording',
                op: 'eq',
                value: '48',
              }),
              group('96', 2, {
                field: 'rate',
                schema: 'recording',
                op: 'eq',
                value: '96',
              }),
            ],
            total: [3],
            truncated: false,
            limit: 1000,
            timezone: null,
          })
        if (by === 'encounter.site')
          return json({
            schema_name: 'recording',
            group_columns: [column('encounter.site', 'site', 'encounter')],
            measure_columns: [count],
            rows: [
              group('Georges', 1, site('Georges')),
              group('Stellwagen', 2, site('Stellwagen')),
            ],
            total: [3],
            truncated: false,
            limit: 1000,
            timezone: null,
          })
        // No grouping: what the suggestions ask (how many different values).
        return json({
          schema_name: 'recording',
          group_columns: [],
          measure_columns: (body.measures as string[]).map((key) => ({
            ...count,
            key,
            measure: key.split(':')[0],
          })),
          rows: [],
          total: (body.measures as string[]).map((m) =>
            m === 'distinct:rate' ? 2 : 400,
          ),
          truncated: false,
          limit: 1000,
          timezone: null,
        })
      }
      return undefined
    }
  })
  afterEach(() => setFieldTypesForTest(null))

  const charts = () => screen.findByRole('region', { name: 'Charts' })
  const bar = async (name: RegExp) =>
    within(await charts()).findByRole('button', { name })

  it('shows the records and the charts at once, the charts counting what is listed', async () => {
    const filter = JSON.stringify({ field: 'rate', op: 'gt', value: '10' })
    renderExplorer(
      {},
      `/collections/hb?schema=recording&q=9&filter=${encodeURIComponent(filter)}`,
    )
    // No switch between them: the table and the charts are both there.
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(await charts()).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: 'Summary' })).toBeNull()
    expect(screen.queryByRole('radio', { name: 'Map' })).toBeNull()
    expect(
      await screen.findByText('How many recordings per site'),
    ).toBeInTheDocument()
    await bar(/Stellwagen/)
    expect(asked('encounter.site')[0].body).toMatchObject({
      collection: 'hb',
      schema_name: 'recording',
      search: '9',
      filter: JSON.parse(filter),
      measures: ['count'],
    })
  })

  it('clicking a bar filters the records; the chart keeps its bars, the chosen lit', async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=recording')
    await user.click(await bar(/Georges/))
    await waitFor(() =>
      expect(JSON.parse(search().get('filter')!)).toEqual(site('Georges')),
    )
    // The table follows, and so does the other chart ...
    await waitFor(() =>
      expect(JSON.parse(lastRecordCall().params.get('filter')!)).toEqual(
        site('Georges'),
      ),
    )
    await waitFor(() =>
      expect(last(asked('rate')).body!.filter).toEqual(site('Georges')),
    )
    // ... but its own chart counts without its own condition.
    expect(asked('encounter.site').every((c) => !c.body!.filter)).toBe(true)
    expect(await bar(/Georges/)).toHaveAttribute('aria-pressed', 'true')
    expect(await bar(/Stellwagen/)).toHaveAttribute('aria-pressed', 'false')
    // A chip says it, and clicking the bar again takes it out.
    expect(
      screen.getByRole('button', { name: /Remove filter .*Georges/ }),
    ).toBeInTheDocument()
    await user.click(await bar(/Georges/))
    await waitFor(() => expect(search().get('filter')).toBeNull())
  })

  it('a bar click and the filter builder edit the same filter', async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=recording')
    await user.click(await bar(/Georges/))
    await user.click(await bar(/Stellwagen/))
    await waitFor(() =>
      expect(JSON.parse(search().get('filter')!)).toEqual({
        ...site('Georges'),
        op: 'in',
        value: ['Georges', 'Stellwagen'],
      }),
    )
    // The builder shows that condition, and removing it there unlights the bars.
    await user.click(screen.getByRole('button', { name: /Filter$/ }))
    const editor = await screen.findByRole('region', { name: 'Edit filters' })
    expect(within(editor).getByDisplayValue('is any of')).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: /Remove filter .*Georges/ }),
    )
    await waitFor(() => expect(search().get('filter')).toBeNull())
    expect(await bar(/Georges/)).toHaveAttribute('aria-pressed', 'false')
  })

  it('leaves a filter a chart cannot show as written, with nothing lit', async () => {
    const complex = {
      or: [
        site('Georges'),
        { field: 'rate', schema: 'recording', op: 'eq', value: '96' },
      ],
    }
    renderExplorer(
      {},
      `/collections/hb?schema=recording&filter=${encodeURIComponent(JSON.stringify(complex))}`,
    )
    expect(await bar(/Georges/)).toHaveAttribute('aria-pressed', 'false')
    expect(await bar(/Stellwagen/)).toHaveAttribute('aria-pressed', 'false')
    // Both charts count the filtered records: the tree is sent whole.
    expect(last(asked('encounter.site')).body!.filter).toEqual(complex)
    expect(last(asked('rate')).body!.filter).toEqual(complex)
  })

  it('adds a chart in two choices, shows its title first, and offers it to the kind', async () => {
    const user = userEvent.setup()
    kindCharts = [bySite]
    renderExplorer({}, '/collections/hb?schema=recording')
    await bar(/Georges/)
    expect(screen.queryByRole('button', { name: /Use for every/ })).toBeNull()
    await user.click(screen.getByRole('button', { name: /Add chart/ }))
    const panel = screen.getByRole('heading', { name: 'New chart' })
      .parentElement!.parentElement!
    await user.selectOptions(
      within(panel).getByLabelText('One bar for each'),
      'rate',
    )
    expect(
      within(panel).getByText('How many recordings per rate'),
    ).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: 'Add chart' }))
    // The change is in the address until it is saved or put back.
    await waitFor(() => expect(search().get('charts')).toContain('rate'))
    await bar(/96/)
    await user.click(
      screen.getByRole('button', { name: 'Use for every Recording list' }),
    )
    await waitFor(() => expect(put).toHaveLength(2))
    expect(put![1]).toMatchObject({ group_by: ['rate'], measures: ['count'] })
    await waitFor(() => expect(search().get('charts')).toBeNull())
  })

  it('puts back the kind’s charts', async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=recording')
    await bar(/Georges/)
    await user.click(
      screen.getByRole('button', {
        name: 'Remove How many recordings per rate',
      }),
    )
    await waitFor(() => expect(search().get('charts')).not.toBeNull())
    await user.click(screen.getByRole('button', { name: 'Put back' }))
    await waitFor(() => expect(search().get('charts')).toBeNull())
    expect(await bar(/96/)).toBeInTheDocument()
  })

  it('keeps Use for every … off for someone who may not change the structure', async () => {
    me = {
      account: { name: 'writer', kind: 'user', manage_url: null },
      permissions: {
        actions: { read: ['project'], write_records: ['project'] },
        all: {},
      },
    }
    renderExplorer(
      {},
      `/collections/hb?schema=recording&charts=${encodeURIComponent('[{"i":"x","by":["rate"],"m":["count"]}]')}`,
    )
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Use for every Recording list' }),
      ).toBeDisabled(),
    )
    expect(screen.getByRole('button', { name: 'Put back' })).toBeEnabled()
  })

  it('suggests charts from the data for a kind with none set', async () => {
    kindCharts = []
    renderExplorer({}, '/collections/hb?schema=recording')
    // rate has 2 different values among those listed; site has 400.
    expect(
      await screen.findByText('How many recordings per rate'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/per site/)).toBeNull()
    // Suggested, not saved: nothing is in the address or sent to the kind.
    expect(search().get('charts')).toBeNull()
    expect(put).toBeNull()
  })

  it('opens a chart large from the address, with its numbers, and Back closes it', async () => {
    const user = userEvent.setup()
    renderExplorer({}, '/collections/hb?schema=recording')
    await bar(/Georges/)
    await user.click(screen.getAllByRole('button', { name: 'Open' })[0])
    await waitFor(() => expect(search().get('chart')).toBe('a'))
    expect(
      await screen.findByRole('button', { name: /Download numbers/ }),
    ).toBeInTheDocument()
    // The records are still on screen beneath it.
    expect(screen.getAllByRole('table').length).toBeGreaterThan(1)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(search().get('chart')).toBeNull())
  })

  it('folds the charts away and brings them back, remembered here', async () => {
    const user = userEvent.setup()
    const first = renderExplorer({}, '/collections/hb?schema=recording')
    await user.click(
      within(await charts()).getByRole('button', { name: 'Hide charts' }),
    )
    expect(screen.queryByRole('region', { name: 'Charts' })).toBeNull()
    expect(screen.getByRole('table')).toBeInTheDocument()
    first.unmount()
    renderExplorer({}, '/collections/hb?schema=recording')
    await screen.findByRole('table')
    expect(screen.queryByRole('region', { name: 'Charts' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Charts' }))
    expect(await charts()).toBeInTheDocument()
  })

  it('a saved filter made from bars comes back as the same filter', async () => {
    const user = userEvent.setup()
    let saved: Record<string, unknown> | null = null
    const inner = override!
    override = (url, method) => {
      if (url.pathname.endsWith('/recording/views') && method === 'POST') {
        saved = calls[calls.length - 1].body!
        return json({
          ...EMPTY_TABLES,
          id: 'v9',
          schema_id: recording.id,
          schema_name: 'recording',
          ...saved,
        })
      }
      if (url.pathname.endsWith('/recording/views') && method === 'GET')
        return json(
          saved
            ? [
                {
                  ...EMPTY_TABLES,
                  id: 'v9',
                  schema_id: recording.id,
                  schema_name: 'recording',
                  ...saved,
                },
              ]
            : [],
        )
      return inner(url, method)
    }
    renderExplorer({}, '/collections/hb?schema=recording')
    await user.click(await bar(/Georges/))
    await user.click(
      await screen.findByRole('button', { name: /Save this filter/ }),
    )
    await user.type(screen.getByLabelText('Name'), 'Georges only')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(saved?.filter_tree).toEqual(site('Georges')))
    // Dropped and applied again, it is the same filter and the bar is lit.
    const chip = () => screen.findByRole('button', { name: /^Georges only$/ })
    await user.click(await chip())
    await waitFor(() => expect(search().get('filter')).toBeNull())
    await user.click(await chip())
    await waitFor(() =>
      expect(JSON.parse(search().get('filter')!)).toEqual(site('Georges')),
    )
    expect(await bar(/Georges/)).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('a map as a chart', () => {
  // The encounter has a location; a recording is placed where its encounter is.
  const geoEncounter: Schema = {
    ...encounter,
    fields: [
      ...encounter.fields,
      {
        ...encounter.fields[0],
        id: 'encounter-place',
        name: 'place',
        type: 'geo',
      },
    ],
  }
  beforeEach(() => {
    setFieldTypesForTest({
      types: [
        {
          type: 'geo',
          label: 'Location',
          description: '',
          stored_as: '',
          entry_hint: '',
          example: '',
          restrictions: [],
          supports_default: false,
          searchable: false,
          measures: ['filled'],
          grouping: null,
          buckets: [],
        },
      ],
      kinds: [],
      summary_measures: [],
    })
    override = (url: URL, method: string) => {
      if (url.pathname === '/api/schemas')
        return json([geoEncounter, recording, selection])
      if (url.pathname === '/api/settings/map')
        return json({ tile_url: null, attribution: null })
      if (url.pathname === '/api/records/points' && method === 'POST')
        return json({
          schema_name: 'encounter',
          field: 'place',
          points: [
            {
              id: 'r1',
              name: 'R1',
              geometry: { type: 'Point', coordinates: [-70, 42] },
            },
          ],
          total: 3,
          truncated: true,
          limit: 1,
        })
      return undefined
    }
  })
  afterEach(() => setFieldTypesForTest(null))

  it('is suggested where the kind, or one above it, has a location, and maps what is listed', async () => {
    const filter = JSON.stringify({ field: 'rate', op: 'eq', value: '96' })
    renderExplorer(
      {},
      `/collections/hb?schema=recording&q=96&filter=${encodeURIComponent(filter)}`,
    )
    expect(await screen.findByText('Where they are')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/records/points')?.body,
      ).toMatchObject({
        collection: 'hb',
        schema_name: 'recording',
        search: '96',
        filter: JSON.parse(filter),
        field: 'place',
        field_schema: 'encounter',
      }),
    )
    expect(
      await within(await screen.findByRole('list', { name: 'map' })).findByText(
        'R1',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('First 1 of 3')).toBeInTheDocument()
  })

  it('is not offered where there is no location anywhere', async () => {
    override = null
    renderExplorer({}, '/collections/hb?schema=selection')
    await screen.findByRole('table')
    expect(screen.queryByText('Where they are')).toBeNull()
  })
})

describe('what this person may do', () => {
  it('shows New switched off, saying why, for someone who may only read', async () => {
    override = (url: URL) => {
      if (url.pathname === '/api/me')
        return json({
          account: { name: 'Dr Example', kind: 'user', manage_url: null },
          permissions: { actions: { read: ['project'] }, all: {} },
        })
      if (url.pathname === '/api/collections/hb')
        return json({
          id: 'c1',
          name: 'hb',
          description: null,
          timezone: null,
          record_count: 0,
          deleted_at: null,
          scope: 'local',
        })
      if (url.pathname.endsWith('/record-counts')) return json({})
      return undefined
    }
    renderExplorer({}, '/collections/hb')
    const button = await screen.findByRole('button', { name: /^New$/ })
    await waitFor(() => expect(button).toBeDisabled())
    expect(button).toHaveAttribute(
      'title',
      'You may not add, change and restore records, and save filters and exports here.',
    )
  })

  describe('searching one field', () => {
    const fieldTypes = (searchable: string[]) => ({
      types: ['string', 'reference'].map((type) => ({
        type,
        label: type,
        description: '',
        stored_as: '',
        entry_hint: '',
        example: '',
        restrictions: [],
        supports_default: true,
        searchable: searchable.includes(type),
        measures: ['filled'],
        grouping: 'value' as const,
        buckets: [],
      })),
      kinds: [],
      summary_measures: [],
    })
    beforeEach(() => {
      const two = schema('encounter', null, ['site', 'observer'])
      two.fields.push({
        ...two.fields[0],
        id: 'enc-ref',
        name: 'boat',
        type: 'reference',
      })
      override = (url: URL) => {
        if (url.pathname === '/api/schemas')
          return json([two, recording, selection])
        return undefined
      }
    })
    beforeEach(() => setFieldTypesForTest(fieldTypes(['string'])))
    afterEach(() => setFieldTypesForTest(null))

    it('offers every searchable field of the listed kind, and sends the one picked', async () => {
      const user = userEvent.setup()
      renderExplorer({}, '/collections/hb?q=stell')
      const pick = await screen.findByRole('combobox', { name: 'Search in' })
      const options = within(pick)
        .getAllByRole('option')
        .map((o) => o.textContent)
      expect(options).toEqual(['In all fields', 'In Site', 'In Observer'])

      await user.selectOptions(pick, 'site')
      expect(search().get('qin')).toBe('site')
      await waitFor(() =>
        expect(lastRecordCall().params.getAll('search_field')).toEqual([
          'site',
        ]),
      )
      expect(lastRecordCall().params.get('search')).toBe('stell')

      await user.selectOptions(pick, '')
      expect(search().get('qin')).toBeNull()
    })
  })
})

describe('checks', () => {
  const blankFilter = {
    or: [
      { field: 'rate', op: 'is_null', schema: 'recording' },
      { field: 'rate', op: 'eq', value: '', schema: 'recording' },
    ],
  }
  const report = {
    records: 3,
    records_with_issues: 2,
    issues: [
      {
        name: 'breaks_rule',
        label: 'Breaks a rule',
        description: 'A stored value the rules refuse now.',
      },
      { name: 'blank', label: 'Required but empty', description: '' },
    ],
    kinds: [
      {
        schema_name: 'recording',
        schema_label: 'Recording',
        records: 3,
        records_with_issues: 2,
        issues: [
          {
            issue: 'breaks_rule',
            field: 'rate',
            field_label: 'Rate',
            count: 2,
            examples: [
              {
                record_id: 'r1',
                record_name: 'R1',
                message: "Field 'rate': 96 exceeds maximum (50)",
              },
            ],
            filter: null,
          },
          {
            issue: 'blank',
            field: 'rate',
            field_label: 'Rate',
            count: 1,
            examples: [],
            filter: blankFilter,
          },
        ],
        blanks: [
          {
            field: 'rate',
            field_label: 'Rate',
            required: true,
            blank: 1,
            filter: blankFilter,
          },
        ],
      },
    ],
  }
  beforeEach(() => {
    override = (url: URL, method: string) => {
      if (url.pathname === '/api/records/quality' && method === 'POST')
        return json(report)
      if (url.pathname === '/api/records/quality/records' && method === 'POST')
        return json({
          items: [
            {
              record_id: 'r1',
              record_name: 'R1',
              schema_name: 'recording',
              field: 'rate',
              message: "Field 'rate': 96 exceeds maximum (50)",
            },
            {
              record_id: 'r2',
              record_name: 'R2',
              schema_name: 'recording',
              field: 'rate',
              message: "Field 'rate': 60 exceeds maximum (50)",
            },
          ],
          total: 2,
          offset: 0,
          limit: 25,
        })
      return undefined
    }
  })

  it('checks exactly what the list shows, and opens the records with an issue', async () => {
    renderExplorer({}, '/collections/hb?schema=recording&q=9')
    // A fact beside the count, counted before it is opened.
    expect(screen.queryByRole('button', { name: 'Check data' })).toBeNull()
    const button = await screen.findByRole('button', { name: '2 problems' })
    await userEvent.click(button)
    expect(search().get('show')).toBe('checks')
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/records/quality')?.body,
      ).toMatchObject({
        collection: 'hb',
        schema_name: 'recording',
        search: '9',
      }),
    )
    expect(await screen.findByText(/of 3 records/)).toBeInTheDocument()
    expect(screen.queryByText('How full each field is')).toBeNull()

    // A line opens its records (held in the address), to tick and edit.
    await userEvent.click(screen.getByText('Breaks a rule'))
    expect(search().get('chk.issue')).toBe('breaks_rule')
    expect(search().get('chk.field')).toBe('rate')
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/records/quality/records')?.body,
      ).toMatchObject({
        issue: 'breaks_rule',
        field: 'rate',
        kind: 'recording',
      }),
    )
    const region = await screen.findByRole('region', {
      name: 'Breaks a rule: Rate',
    })
    expect(within(region).getByText('R2')).toBeInTheDocument()
    await userEvent.click(within(region).getAllByRole('checkbox')[1])
    await userEvent.click(within(region).getByRole('button', { name: 'Edit…' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('lists the records that leave a field empty in the explorer', async () => {
    renderExplorer({}, '/collections/hb?schema=recording&show=checks')
    await userEvent.click(await screen.findByText('Required but empty'))
    const region = await screen.findByRole('region', {
      name: 'Required but empty: Rate',
    })
    await userEvent.click(
      within(region).getByRole('button', { name: 'Show in the list' }),
    )
    await waitFor(() => expect(search().get('show')).toBeNull())
    expect(JSON.parse(search().get('filter')!)).toEqual(blankFilter)
  })

  it('goes back to the records from the checks', async () => {
    renderExplorer({}, '/collections/hb?schema=recording&show=checks')
    await userEvent.click(
      await screen.findByRole('button', { name: 'Back to records' }),
    )
    await waitFor(() => expect(search().get('show')).toBeNull())
  })
})
