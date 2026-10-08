import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { LibraryPanel } from './LibraryPanel'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const item = (over: Record<string, unknown>) => ({
  kind: 'workflow',
  name: 'uses-shared',
  filename: 'uses-shared.yaml',
  sha256: 'a'.repeat(64),
  size: 10,
  version: 2,
  title: 'Uses shared',
  description: null,
  provides: null,
  needs: ['project.shared_step'],
  triggers: ['record_created on encounter'],
  published_by: 'laptop',
  published_at: '2026-10-08T00:00:00Z',
  here: 'absent',
  missing: [],
  content: null,
  ...over,
})

const plugin = item({
  kind: 'plugin',
  name: 'shared_step',
  filename: 'shared_step.py',
  provides: 'project.shared_step',
  needs: [],
  triggers: [],
  sha256: 'b'.repeat(64),
})

let plan: Record<string, unknown>
let installs: unknown[]

beforeEach(() => {
  installs = []
  plan = {
    steps: [
      { item: plugin, path: '_civex/plugins/shared_step.py', here: 'absent' },
      {
        item: item({}),
        path: '_civex/workflows/uses-shared.yaml',
        here: 'absent',
      },
    ],
    blocked: [],
    warnings: ['uses-shared runs by itself: record_created on encounter.'],
    runs_code: true,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      if (url.pathname === '/api/remote')
        return json({ serving: false, remote: 'https://hub.test' })
      if (url.pathname === '/api/remote/library')
        return json([plugin, item({})])
      if (url.pathname === '/api/remote/library/plugin/shared_step')
        return json({ ...plugin, content: 'class Plugin: ...' })
      if (url.pathname.endsWith('/install') && method === 'GET')
        return json(plan)
      if (url.pathname.endsWith('/install') && method === 'POST') {
        installs.push(JSON.parse(String(init?.body)))
        return json({ ...plan, warnings: plan.warnings })
      }
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <LibraryPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openInstall(user: ReturnType<typeof userEvent.setup>) {
  const row = (await screen.findByText('uses-shared.yaml')).closest('tr')!
  await user.click(within(row).getByRole('button', { name: 'Install…' }))
  return screen.findByRole('dialog')
}

describe('LibraryPanel', () => {
  it('lists what is shared, what starts by itself and where it stands here', async () => {
    renderIt()
    expect(await screen.findByText('uses-shared.yaml')).toBeTruthy()
    expect(
      screen.getByText('Runs by itself: record_created on encounter'),
    ).toBeTruthy()
    expect(screen.getAllByText('Not here')).toHaveLength(2)
  })

  it('installs plugin code only once the person says they trust it', async () => {
    const user = userEvent.setup()
    renderIt()
    const dialog = await openInstall(user)

    expect(
      await within(dialog).findByText('_civex/plugins/shared_step.py'),
    ).toBeTruthy()
    const install = within(dialog).getByRole('button', { name: 'Install' })
    expect(install).toHaveProperty('disabled', true)

    await user.click(within(dialog).getByText('Read the code'))
    expect(await within(dialog).findByText('class Plugin: ...')).toBeTruthy()

    await user.click(
      within(dialog).getByText("I've read it and trust whoever published it"),
    )
    expect(install).toHaveProperty('disabled', false)
    await user.click(install)
    await waitFor(() =>
      expect(installs).toEqual([{ replace: false, with_plugins: true }]),
    )
    expect(await within(dialog).findByText(/Installed/)).toBeTruthy()
  })

  it('installs nothing while the plan says why it can not', async () => {
    plan = {
      ...plan,
      runs_code: false,
      blocked: ['uses-shared.yaml is here already, with different contents.'],
    }
    const user = userEvent.setup()
    renderIt()
    const dialog = await openInstall(user)
    expect(
      await within(dialog).findByText(/with different contents/),
    ).toBeTruthy()
    expect(
      within(dialog).getByRole('button', { name: 'Install' }),
    ).toHaveProperty('disabled', true)
  })
})
