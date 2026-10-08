import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui'
import { WorkflowsPanel } from './WorkflowsPanel'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const local = (stem: string, runs_on: string[] = []) => ({
  name: stem,
  description: `About ${stem}`,
  steps: 2,
  filename: `${stem}.yaml`,
  stem,
  record_schema: null,
  inputs: null,
  runs_on,
})

const shared = (name: string, over: Record<string, unknown> = {}) => ({
  kind: 'workflow',
  name,
  filename: `${name}.yaml`,
  sha256: 'a'.repeat(64),
  size: 1,
  version: 2,
  title: name,
  description: null,
  provides: null,
  needs: [],
  pins: {},
  triggers: [],
  published_by: 'laptop',
  published_at: null,
  history: [],
  here: 'absent',
  local_version: null,
  missing: [],
  content: null,
  ...over,
})

let sharing: boolean
let publishes: unknown[]

beforeEach(() => {
  sharing = true
  publishes = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/workflows')
        return json([
          local('tidy-sites', ['record_created on encounter']),
          local('older-one'),
        ])
      if (url.pathname === '/api/remote')
        return json({
          serving: false,
          remote: sharing ? 'https://hub.test' : null,
        })
      if (url.pathname === '/api/remote/library')
        return json(
          sharing
            ? [
                shared('older-one', { here: 'older', local_version: 1 }),
                shared('from-elsewhere', {
                  triggers: ['record_updated on sample'],
                }),
              ]
            : [],
        )
      if (url.pathname === '/api/remote/library/publish') {
        publishes.push(JSON.parse(String(init?.body)))
        return json({
          items: [shared('tidy-sites', { version: 1 })],
          warnings: [],
        })
      }
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(url = '/workflows') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <WorkflowsPanel onRun={() => {}} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const rowOf = async (name: string) =>
  (await screen.findByText(name)).closest('tr')!

describe('Workflows list', () => {
  it('lists this project and the library together, with how each stands', async () => {
    renderIt()
    const mine = await rowOf('tidy-sites')
    expect(within(mine).getByText('Not shared')).toBeTruthy()
    expect(within(mine).getByText('record_created on encounter')).toBeTruthy()
    expect(
      within(await rowOf('older-one')).getByText('v1 here · v2 available'),
    ).toBeTruthy()
    const theirs = await rowOf('from-elsewhere')
    expect(within(theirs).getByText('In the library · v2')).toBeTruthy()
    expect(
      within(theirs).getByRole('button', { name: 'Install…' }),
    ).toBeTruthy()
    expect(within(theirs).queryByRole('button', { name: 'Run' })).toBeNull()
  })

  it('searches and filters by how a workflow stands', async () => {
    renderIt('/workflows?show=library')
    expect(await screen.findByText('from-elsewhere')).toBeTruthy()
    expect(screen.queryByText('tidy-sites')).toBeNull()
  })

  it('finds a workflow by what starts it', async () => {
    renderIt('/workflows?q=sample')
    expect(await screen.findByText('from-elsewhere')).toBeTruthy()
    expect(screen.queryByText('tidy-sites')).toBeNull()
  })

  it('publishes from a row', async () => {
    const user = userEvent.setup()
    renderIt()
    const mine = await rowOf('tidy-sites')
    await user.click(
      within(mine).getByRole('button', { name: 'More for tidy-sites' }),
    )
    await user.click(await screen.findByText('Publish…'))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Publish' }))
    await waitFor(() =>
      expect(publishes).toEqual([
        { kind: 'workflow', name: 'tidy-sites', with_plugins: true },
      ]),
    )
    expect(
      await within(dialog).findByText(/tidy-sites.yaml \(v1\)/),
    ).toBeTruthy()
  })

  it('has no sharing column or library rows while not sharing', async () => {
    sharing = false
    renderIt()
    expect(await screen.findByText('tidy-sites')).toBeTruthy()
    expect(screen.queryByText('Sharing')).toBeNull()
    expect(screen.queryByText('from-elsewhere')).toBeNull()
  })
})
