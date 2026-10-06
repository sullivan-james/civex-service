import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { exported, fakeServer, finishExport, json } from '../files/testSupport'
import { SavedExports } from './SavedExports'
import { definition, SCHEMAS } from './exportsTestSupport'

afterEach(() => vi.unstubAllGlobals())

const COLLECTIONS = [
  { id: 'c1', name: 'hb', description: null, record_count: 3, schemas: [] },
  { id: 'c2', name: 'other', description: null, record_count: 0, schemas: [] },
]

const SHEETS = definition({
  id: 'd2',
  name: 'Selection sheets',
  schema_id: 'recording',
  schema_name: 'recording',
  holder: 'selection',
  fields: [],
  files_layout: 'tree',
  tables: [
    {
      format: 'csv',
      kind: 'selection',
      where: 'selection',
      shape: 'fields',
      columns: null,
    },
  ],
})

function serve(defs: unknown[] = [definition(), SHEETS], extra = {}) {
  return fakeServer({
    '/api/file-access/definitions': defs,
    '/api/collections': COLLECTIONS,
    '/api/schemas': SCHEMAS,
    '/api/store/volumes': [],
    '/api/file-access/exports': [],
    '/api/file-access/export': exported(),
    '/api/schemas/encounter/exports': () => json(definition(), 201),
    ...extra,
  })
}

function renderAt(url = '/exports') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <SavedExports schemas={SCHEMAS} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const rowOf = async (name: string) =>
  (await screen.findByText(name)).closest('tr')!

describe('the saved exports, as a list', () => {
  it('is a table of name, what it starts from and what it takes', async () => {
    serve()
    renderAt()

    const table = await screen.findByRole('table')
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((h) => h.textContent)
    expect(headers).toEqual(
      expect.arrayContaining(['Name', 'Starts from', 'Takes']),
    )
    const row = await rowOf('Selection sheets')
    expect(within(row).getByText('Recording')).toBeInTheDocument()
    expect(
      within(row).getByText(/CSV of Selection in each record’s folder/),
    ).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/saved with/i)
  })

  it('asks for every export', async () => {
    const calls = serve()
    renderAt()
    await screen.findByText('Contours')

    expect(calls.some((c) => c.path === '/api/file-access/definitions')).toBe(
      true,
    )
  })

  it('searches by name', async () => {
    serve()
    renderAt()
    await screen.findByText('Contours')

    await userEvent.type(
      screen.getByPlaceholderText('Search exports'),
      'sheets',
    )

    await waitFor(() => expect(screen.queryByText('Contours')).toBeNull())
    expect(screen.getByText('Selection sheets')).toBeInTheDocument()
  })

  it('narrows to what starts from one kind of record, from the address too', async () => {
    serve()
    renderAt('/exports?schema=recording')

    expect(await screen.findByText('Selection sheets')).toBeInTheDocument()
    expect(screen.queryByText('Contours')).toBeNull()
    expect(
      (screen.getByLabelText('Starts from…') as HTMLSelectElement).value,
    ).toBe('recording')
  })

  it('says when nothing matches, and when there are none at all', async () => {
    serve()
    renderAt('/exports?q=zzz')
    expect(await screen.findByText('No exports match')).toBeInTheDocument()
  })

  it('says what an export is when there are none', async () => {
    serve([])
    renderAt()

    expect(await screen.findByText('No exports yet')).toBeInTheDocument()
    expect(
      screen.getByText(/choose which files and tables/i),
    ).toBeInTheDocument()
  })

  it('sorts by a column header', async () => {
    serve()
    renderAt()
    await screen.findByText('Contours')

    await userEvent.click(screen.getByRole('button', { name: /^starts from/i }))
    await userEvent.click(screen.getByRole('button', { name: /^starts from/i }))

    const names = screen
      .getAllByRole('row')
      .slice(1)
      .map((r) => r.textContent ?? '')
    expect(names[0]).toContain('Selection sheets') // Recording before Encounter, descending
  })
})

describe('running', () => {
  it('is not offered until a collection is chosen, and says why', async () => {
    serve()
    renderAt()
    const row = await rowOf('Contours')

    const run = within(row).getByRole('button', { name: 'Run…' })
    expect(run).toBeDisabled()
    expect(run).toHaveAttribute(
      'title',
      expect.stringMatching(/choose a collection/i),
    )
  })

  it('runs a saved export on the chosen collection', async () => {
    const calls = serve()
    renderAt('/exports?collection=hb')
    const row = await rowOf('Contours')

    await userEvent.click(within(row).getByRole('button', { name: 'Run…' }))
    await finishExport('folder', 0)

    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/file-access/export')).toBe(
        true,
      ),
    )
    expect(
      calls.find((c) => c.path === '/api/file-access/export')!.body,
    ).toMatchObject({
      export: 'encounter/Contours',
      collection: 'hb',
      name: 'hb-Contours',
    })
  })
})

describe('making, changing and deleting', () => {
  it('has a link to a page of its own for a new export', async () => {
    serve()
    renderAt()
    await screen.findByText('Contours')

    expect(screen.getByRole('link', { name: /new export/i })).toHaveAttribute(
      'href',
      '/exports/new',
    )
  })

  it('starts a new export from the kind filtered to, if one is', async () => {
    serve()
    renderAt('/exports?schema=recording')
    await screen.findByText('Selection sheets')

    expect(screen.getByRole('link', { name: /new export/i })).toHaveAttribute(
      'href',
      '/exports/new?schema=recording',
    )
  })

  it('links each export to a page of its own, from its name and from Edit', async () => {
    serve()
    renderAt()
    const row = await rowOf('Selection sheets')

    expect(within(row).getByRole('link', { name: 'Edit' })).toHaveAttribute(
      'href',
      '/exports/recording/Selection%20sheets',
    )
    // The whole row leads there too, as a real link (open in a new tab works).
    expect(
      within(row)
        .getAllByRole('link')
        .some(
          (a) =>
            a.getAttribute('href') === '/exports/recording/Selection%20sheets',
        ),
    ).toBe(true)
  })

  it('deletes an export from the schema it starts from', async () => {
    const calls = serve(undefined, {
      '/api/schemas/recording/exports/Selection%20sheets': () =>
        new Response(null, { status: 204 }),
    })
    renderAt()
    const row = await rowOf('Selection sheets')

    await userEvent.click(within(row).getByRole('button', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete export' }))

    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === 'DELETE' &&
            c.path === '/api/schemas/recording/exports/Selection%20sheets',
        ),
      ).toBe(true),
    )
  })
})
