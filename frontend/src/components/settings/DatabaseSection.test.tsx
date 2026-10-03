import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import DatabaseSection from './DatabaseSection'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const STATUS = {
  url: 'sqlite:////p/_civex/civex.db',
  dialect: 'sqlite',
  docker_managed: false,
  migration: {
    current_revision: 'abc',
    head_revision: 'abc',
    up_to_date: true,
    error: null,
  },
  docker: null,
}
const SQLITE = {
  label: 'SQLite file',
  dialect: 'sqlite',
  location: 'sqlite:////p/_civex/civex.db',
  reachable: true,
  error: null,
  records: 337976,
  rows: 700000,
  size_bytes: 883933184,
}
const DOCKER = {
  label: 'Docker PostgreSQL',
  dialect: 'postgresql',
  location: 'postgresql+psycopg2://postgres@localhost:5432/civex',
  reachable: true,
  error: null,
  records: 0,
  rows: 0,
  size_bytes: 8000000,
}
const preflight = (over: Record<string, unknown> = {}) => ({
  source: SQLITE,
  target: DOCKER,
  target_label: 'Docker PostgreSQL',
  can_proceed: true,
  problems: [],
  warnings: [],
  estimate_seconds: 40,
  ...over,
})
const record = (over: Record<string, unknown> = {}) => ({
  id: 'm1',
  started_at: '2026-10-01T10:00:00Z',
  finished_at: '2026-10-01T10:01:00Z',
  status: 'done',
  source_label: 'SQLite file',
  source_location: 'sqlite:////p/_civex/civex.db',
  target_label: 'Docker PostgreSQL',
  target_location: 'postgresql+psycopg2://postgres@localhost:5432/civex',
  seconds: 12.3,
  counts: { records: 337976, audit_log: 338019 },
  error: null,
  problems: [],
  reverted_at: null,
  ...over,
})
const progress = (rows_done: number) => ({
  phase: 'copy',
  table: 'records',
  rows_done,
  rows_total: 1000,
  tables_done: 3,
  tables_total: 16,
  message: 'Copying records',
})

type Handler = (url: URL, init?: RequestInit) => Response | undefined
let calls: { method: string; path: string; body: unknown }[]
let overrides: Handler[]

beforeEach(() => {
  calls = []
  overrides = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: url.pathname,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      for (const h of overrides) {
        const r = h(url, init)
        if (r) return r
      }
      if (url.pathname === '/api/db/status') return json(STATUS)
      if (url.pathname === '/api/db/summary') return json(SQLITE)
      if (url.pathname === '/api/db/moves') return json([])
      if (url.pathname === '/api/db/move/preflight') return json(preflight())
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <DatabaseSection />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openWizard(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole('button', { name: /Move to another database/ }),
  )
  return screen.getByRole('dialog', { name: 'Move database' })
}

describe('current database', () => {
  it('says what the database is, where, and how big', async () => {
    renderIt()
    expect(await screen.findByText('SQLite file')).toBeInTheDocument()
    expect(screen.getByText(/337,976 records · 843\.0 MB/)).toBeInTheDocument()
    expect(
      screen.getByText(/Connected · schema up to date/),
    ).toBeInTheDocument()
  })

  it('offers a schema update only when one is pending', async () => {
    overrides.push((url) =>
      url.pathname === '/api/db/status'
        ? json({
            ...STATUS,
            migration: { ...STATUS.migration, up_to_date: false },
          })
        : undefined,
    )
    renderIt()
    expect(
      await screen.findByText(/structure is out of date/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Update it' }),
    ).toBeInTheDocument()
  })

  it('warns plainly when the database can’t be reached', async () => {
    overrides.push((url) =>
      url.pathname === '/api/db/summary'
        ? json({ ...SQLITE, reachable: false, error: 'connection refused' })
        : undefined,
    )
    renderIt()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Can’t reach this database: connection refused/,
    )
  })
})

describe('moving the database', () => {
  it('walks through choosing, reviewing, moving and finishing', async () => {
    const user = userEvent.setup()
    // The move stays "running" until the test has seen the progress, then
    // finishes. (Counting polls instead made the running frame last ~500ms, so
    // on a slow machine the test could miss it entirely.)
    let finished = false
    overrides.push((url, init) => {
      if (url.pathname === '/api/db/move' && init?.method === 'POST')
        return json(
          {
            id: 'j1',
            status: 'running',
            progress: progress(0),
            error: null,
            record: null,
          },
          202,
        )
      if (url.pathname === '/api/db/move/j1') {
        return json(
          !finished
            ? {
                id: 'j1',
                status: 'running',
                progress: progress(400),
                error: null,
                record: null,
              }
            : {
                id: 'j1',
                status: 'done',
                progress: progress(1000),
                error: null,
                record: record(),
              },
        )
      }
      return undefined
    })
    renderIt()
    const dialog = await openWizard(user)

    // Step 1: Docker is the default destination.
    expect(
      within(dialog).getByRole('radio', { name: /Docker PostgreSQL/ }),
    ).toBeChecked()
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    // Step 2: what will happen, in plain terms.
    expect(
      await within(dialog).findByText(/From \(now in use\)/),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(/337,976 records · 843\.0 MB/),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(/original is left exactly as it is/),
    ).toBeInTheDocument()
    expect(within(dialog).getByText(/about 40 seconds/)).toBeInTheDocument()
    await user.click(
      within(dialog).getByRole('button', { name: 'Move my data' }),
    )

    // Step 3: progress.
    expect(await within(dialog).findByRole('progressbar')).toBeInTheDocument()
    expect(
      await within(dialog).findByText(/400 of 1,000 rows/),
    ).toBeInTheDocument()
    finished = true

    // Step 4: verified, and where everything is.
    expect(
      await within(dialog).findByText(
        /Your data is now in Docker PostgreSQL/,
        {},
        { timeout: 4000 },
      ),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(/checked against the original/),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(/The original is untouched at/),
    ).toBeInTheDocument()
    expect(
      calls.find((c) => c.path === '/api/db/move' && c.method === 'POST')?.body,
    ).toEqual({
      kind: 'docker',
    })
  })

  it('shows why a move can’t happen, and won’t start it', async () => {
    const user = userEvent.setup()
    overrides.push((url) =>
      url.pathname === '/api/db/move/preflight'
        ? json(
            preflight({
              can_proceed: false,
              problems: ['The destination isn’t empty (12 records).'],
            }),
          )
        : undefined,
    )
    renderIt()
    const dialog = await openWizard(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      /isn’t empty/,
    )
    expect(
      within(dialog).getByRole('button', { name: 'Move my data' }),
    ).toBeDisabled()
  })

  it('asks for server details, and checks the connection in plain words', async () => {
    const user = userEvent.setup()
    overrides.push((url) =>
      url.pathname === '/api/db/test-connection'
        ? json({
            ok: false,
            error: 'The server rejected the user name or password.',
          })
        : undefined,
    )
    renderIt()
    const dialog = await openWizard(user)
    await user.click(
      within(dialog).getByRole('radio', { name: /PostgreSQL server/ }),
    )

    // Nothing to go on with until the essentials are in.
    expect(within(dialog).getByRole('button', { name: 'Next' })).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Database'), 'civex')
    expect(within(dialog).getByRole('button', { name: 'Next' })).toBeEnabled()
    await user.type(within(dialog).getByLabelText('User'), 'ada')
    await user.type(within(dialog).getByLabelText('Password'), 's3cret')
    await user.click(
      within(dialog).getByRole('button', { name: 'Check connection' }),
    )

    expect(await within(dialog).findByRole('status')).toHaveTextContent(
      'The server rejected the user name or password.',
    )
    expect(
      calls.find((c) => c.path === '/api/db/test-connection')?.body,
    ).toMatchObject({
      kind: 'postgres',
      host: 'localhost',
      port: 5432,
      database: 'civex',
      user: 'ada',
      password: 's3cret',
    })
  })

  it('can take a pasted connection URL instead of separate fields', async () => {
    const user = userEvent.setup()
    renderIt()
    const dialog = await openWizard(user)
    await user.click(
      within(dialog).getByRole('radio', { name: /PostgreSQL server/ }),
    )
    await user.click(
      within(dialog).getByRole('button', { name: /Paste a connection URL/ }),
    )
    await user.type(
      within(dialog).getByLabelText('Connection URL'),
      'postgresql+psycopg2://u:p@h:5432/d',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    expect(
      calls.find((c) => c.path === '/api/db/move/preflight')?.body,
    ).toEqual({ kind: 'postgres', url: 'postgresql+psycopg2://u:p@h:5432/d' })
  })

  it('says nothing changed when a move fails', async () => {
    const user = userEvent.setup()
    overrides.push((url, init) => {
      if (url.pathname === '/api/db/move' && init?.method === 'POST')
        return json(
          {
            id: 'j2',
            status: 'running',
            progress: progress(0),
            error: null,
            record: null,
          },
          202,
        )
      if (url.pathname === '/api/db/move/j2')
        return json({
          id: 'j2',
          status: 'failed',
          progress: progress(500),
          error: 'The copy didn’t match the original, so nothing was switched.',
          record: record({
            status: 'failed',
            problems: [
              'records: 337976 rows in the original, 337975 in the copy',
            ],
          }),
        })
      return undefined
    })
    renderIt()
    const dialog = await openWizard(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(
      await within(dialog).findByRole('button', { name: 'Move my data' }),
    )

    expect(await within(dialog).findByText(/didn’t finish/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Nothing was changed/)).toBeInTheDocument()
    expect(within(dialog).getByText(/337975 in the copy/)).toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: 'Try again' }),
    ).toBeInTheDocument()
  })

  it('can cancel a move that is running', async () => {
    const user = userEvent.setup()
    overrides.push((url, init) => {
      if (url.pathname === '/api/db/move' && init?.method === 'POST')
        return json(
          {
            id: 'j3',
            status: 'running',
            progress: progress(10),
            error: null,
            record: null,
          },
          202,
        )
      if (url.pathname === '/api/db/move/j3')
        return json({
          id: 'j3',
          status: 'running',
          progress: progress(10),
          error: null,
          record: null,
        })
      return undefined
    })
    renderIt()
    const dialog = await openWizard(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(
      await within(dialog).findByRole('button', { name: 'Move my data' }),
    )
    await user.click(
      await within(dialog).findByRole('button', { name: 'Cancel move' }),
    )

    expect(
      calls.some(
        (c) => c.path === '/api/db/move/j3/cancel' && c.method === 'POST',
      ),
    ).toBe(true)
  })
})

describe('move history', () => {
  it('lists past moves and switches back only from the newest completed one', async () => {
    const user = userEvent.setup()
    overrides.push((url, init) => {
      if (url.pathname === '/api/db/moves')
        return json([
          record({ id: 'new' }),
          record({ id: 'old', started_at: '2026-09-01T10:00:00Z' }),
          record({ id: 'bad', status: 'failed', error: 'disk full' }),
        ])
      if (
        url.pathname === '/api/db/moves/new/revert' &&
        init?.method === 'POST'
      )
        return json(STATUS)
      return undefined
    })
    renderIt()
    await user.click(await screen.findByRole('tab', { name: /History/ }))

    expect(screen.getAllByRole('button', { name: 'Switch back' })).toHaveLength(
      1,
    )
    expect(screen.getByText(/disk full/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Switch back' }))
    const confirm = await screen.findByRole('dialog', {
      name: /Switch back to the previous database/,
    })
    expect(
      within(confirm).getByText(/Nothing is copied back/),
    ).toBeInTheDocument()
    await user.click(
      within(confirm).getByRole('button', { name: 'Switch back' }),
    )

    expect(
      calls.some(
        (c) => c.path === '/api/db/moves/new/revert' && c.method === 'POST',
      ),
    ).toBe(true)
  })

  it('shows nothing when there is no history', async () => {
    renderIt()
    await screen.findByText('SQLite file')
    expect(
      screen.queryByRole('tab', { name: /History/ }),
    ).not.toBeInTheDocument()
  })
})

describe('advanced', () => {
  it('keeps the rare controls out of the way until asked', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('SQLite file')
    expect(
      screen.queryByText('Use an existing database'),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Advanced' }))

    expect(screen.getByText('Use an existing database')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'More information' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/without copying/)
  })
})
