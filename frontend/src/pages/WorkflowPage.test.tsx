import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui'
import WorkflowPage from './WorkflowPage'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })

const version = (v: number, pins: Record<string, number>) => ({
  version: v,
  sha256: String(v).repeat(64),
  published_by: 'laptop',
  published_at: '2026-10-08T00:00:00Z',
  pins,
})

const shared = (name: string, over: Record<string, unknown> = {}) => ({
  kind: 'workflow',
  name,
  filename: `${name}.yaml`,
  sha256: '3'.repeat(64),
  size: 1,
  version: 3,
  title: name,
  description: 'Shared description',
  provides: null,
  needs: ['project.shared_step'],
  pins: { 'project.shared_step': 2 },
  triggers: [],
  published_by: 'laptop',
  published_at: null,
  history: [
    version(3, { 'project.shared_step': 2 }),
    version(2, { 'project.shared_step': 1 }),
    version(1, { 'project.shared_step': 1 }),
  ],
  here: 'older',
  local_version: 2,
  missing: [],
  content: 'name: from-elsewhere\nsteps: []\n',
  ...over,
})

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/workflows')
        return json([
          {
            name: 'tidy',
            description: null,
            steps: 1,
            filename: 'tidy.yaml',
            stem: 'tidy',
            record_schema: null,
            inputs: null,
            runs_on: ['record_created on encounter'],
          },
        ])
      if (url.pathname === '/api/remote')
        return json({ serving: false, remote: 'https://hub.test' })
      if (url.pathname === '/api/remote/library')
        return json([
          shared('tidy'),
          shared('from-elsewhere', { here: 'absent', local_version: null }),
          {
            ...shared('shared_step'),
            kind: 'plugin',
            provides: 'project.shared_step',
            version: 2,
            local_version: 1,
            here: 'older',
          },
        ])
      if (url.pathname === '/api/remote/library/workflow/from-elsewhere')
        return json(shared('from-elsewhere'))
      if (url.pathname === '/api/plugins') return json([])
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route path="/workflows/:stem" element={<WorkflowPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('WorkflowPage', () => {
  it('shows every version, which one is here, and what each uses', async () => {
    renderAt('/workflows/tidy?tab=sharing')
    expect(await screen.findAllByText('v2 here · v3 available')).toHaveLength(2)
    const rows = (await screen.findAllByRole('row')).slice(1)
    const [v3, v2, v1] = rows
    expect(within(v3).getByRole('button', { name: 'Update…' })).toBeTruthy()
    expect(within(v2).getByText('Here')).toBeTruthy()
    expect(
      within(v2).queryByRole('button', { name: /Update|Roll back/ }),
    ).toBeNull()
    expect(within(v1).getByRole('button', { name: 'Roll back…' })).toBeTruthy()
    expect(within(v3).getByText('project.shared_step v2')).toBeTruthy()
    // The plugin the newest version uses, and where it stands here.
    expect(screen.getByText('v1 here')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Run' })).toBeTruthy()
  })

  it('has a page for a workflow only in the library, to install it from', async () => {
    renderAt('/workflows/from-elsewhere')
    expect(await screen.findByText(/Not installed here/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Install…' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Run' })).toBeNull()
  })
})
