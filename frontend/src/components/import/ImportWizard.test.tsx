import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { filesApi } from '../../api/files'
import { ToastProvider } from '../ui'
import { ImportWizard } from './ImportWizard'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const SHEET = {
  filename: 'people.csv',
  sheets: [],
  sheet: null,
  total: 3,
  columns: [
    { heading: 'ID', label: 'ID', key: 'id', dtype: 'string', blanks: 0 },
    { heading: 'Age', label: 'Age', key: 'age', dtype: 'integer', blanks: 0 },
  ],
  rows: [
    ['007', '31'],
    ['012', 'x'],
    ['100', '40'],
  ],
}
const part = (over: object) => ({
  start: 0,
  read: 3,
  created: 2,
  updated: 0,
  unchanged: 0,
  skipped: 1,
  problems: ["Row 3: age: 'x' is not a whole number"],
  done: true,
  ...over,
})

let runs: {
  check: boolean
  batch: string | null
  body: Record<string, unknown>
}[]
let failSave: boolean

beforeEach(() => {
  runs = []
  failSave = false
  vi.spyOn(filesApi, 'uploadBatch').mockImplementation(async (files, on) => {
    on?.({ loaded: files[0].size, total: files[0].size, saving: false })
    return {
      files: [
        {
          sha256: 'abc',
          filename: files[0].name,
          size: files[0].size,
          volume: 'default',
        },
      ],
      stopped: null,
    }
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const body = init?.body ? JSON.parse(String(init.body)) : null
      if (url.pathname === '/api/schemas') return json([])
      if (url.pathname === '/api/import/inspect') return json(SHEET)
      if (url.pathname === '/api/audit/batches')
        return json({ id: 'batch1', kind: 'import' }, 201)
      if (url.pathname === '/api/import/run') {
        const headers = new Headers(init?.headers as HeadersInit)
        runs.push({
          check: body.check,
          batch: headers.get('X-Civex-Batch'),
          body,
        })
        if (!body.check && failSave)
          return json({ detail: 'The connection was lost.' }, 500)
        return json(part({}))
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderWizard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>
          <ImportWizard
            collection="study"
            collectionId="c1"
            recordsHref={(kind) => `/collections/c1?schema=${kind}`}
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

async function chooseFile() {
  const user = userEvent.setup()
  const input = screen.getByLabelText('Spreadsheet file')
  await user.upload(
    input,
    new File(['ID,Age\n007,31\n'], 'people.csv', { type: 'text/csv' }),
  )
  await screen.findByText('Where do the columns go?')
  return user
}

describe('ImportWizard', () => {
  it('goes from the file to the columns, a check and the import', async () => {
    renderWizard()
    const user = await chooseFile()

    // A new kind named after the file, with a field made for each column.
    expect(screen.getByLabelText('Name of the new kind of record')).toHaveValue(
      'People',
    )
    expect(screen.getByLabelText('What Age holds')).toHaveValue('integer')
    // The type is the person's to change.
    await user.selectOptions(screen.getByLabelText('What Age holds'), 'string')
    await user.selectOptions(screen.getByLabelText('What Age holds'), 'integer')

    await user.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText("Rows that won't be saved")
    expect(
      screen.getByText("Row 3: age: 'x' is not a whole number", {
        selector: 'li',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('To add').nextSibling).toHaveTextContent('2')
    expect(screen.getByText('Not saved').nextSibling).toHaveTextContent('1')
    expect(runs.map((r) => r.check)).toEqual([true])
    expect(runs[0].body.kind).toBe('people')
    expect(runs[0].body.kind_label).toBe('People')

    await user.click(screen.getByRole('button', { name: 'Import 2 rows' }))
    await screen.findByText('Done')
    // Saved in one event of history, after a check that kept nothing.
    expect(runs.map((r) => [r.check, r.batch])).toEqual([
      [true, null],
      [false, 'batch1'],
    ])
    expect(screen.getByText('2 added.')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'See the records' }),
    ).toHaveAttribute('href', '/collections/c1?schema=people')
  })

  it('leaves a column out and cannot go on with none', async () => {
    renderWizard()
    const user = await chooseFile()
    await user.selectOptions(screen.getByLabelText('Where ID goes'), '__skip__')
    await user.selectOptions(
      screen.getByLabelText('Where Age goes'),
      '__skip__',
    )
    expect(screen.getByRole('button', { name: 'Check' })).toBeDisabled()
    expect(
      screen.getAllByText('Choose at least one column to bring in.').length,
    ).toBeGreaterThan(0)
  })

  it('offers to match rows by a column and says what happens', async () => {
    renderWizard()
    const user = await chooseFile()
    await user.selectOptions(
      screen.getByLabelText(
        'A row is a record already saved when this matches',
      ),
      'ID',
    )
    await user.click(screen.getByRole('radio', { name: 'Leave it' }))
    await user.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText("Rows that won't be saved")
    expect(runs[0].body.match_on).toEqual(['id'])
    expect(runs[0].body.if_exists).toBe('skip')
  })

  it('says so when the import stops, and carries on from where it got to', async () => {
    renderWizard()
    const user = await chooseFile()
    await user.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText("Rows that won't be saved")
    failSave = true
    await user.click(screen.getByRole('button', { name: 'Import 2 rows' }))
    await screen.findByText('The connection was lost.')
    expect(screen.getByText(/already in/)).toBeInTheDocument()
    failSave = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByText('Done')
    // The same batch of history: one event, however many tries.
    const saves = runs.filter((r) => !r.check)
    expect(new Set(saves.map((r) => r.batch))).toEqual(new Set(['batch1']))
  })

  it('shows what is wrong with a file the server cannot read', async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/schemas') return json([])
      return json({ detail: 'There is nothing in this file to bring in.' }, 422)
    })
    renderWizard()
    const user = userEvent.setup()
    await user.upload(
      screen.getByLabelText('Spreadsheet file'),
      new File([''], 'empty.csv'),
    )
    await waitFor(() =>
      expect(
        screen.getByText('There is nothing in this file to bring in.'),
      ).toBeInTheDocument(),
    )
  })
})
