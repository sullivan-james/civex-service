import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LibraryInstallDialog } from './LibraryInstallDialog'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })

const item = (over: Record<string, unknown>) => ({
  kind: 'workflow',
  name: 'uses-shared',
  filename: 'uses-shared.yaml',
  sha256: 'a'.repeat(64),
  size: 1,
  version: 2,
  title: null,
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

const plugin = item({
  kind: 'plugin',
  name: 'shared_step',
  filename: 'shared_step.py',
  provides: 'project.shared_step',
  version: 3,
})

let plans: URLSearchParams[]
let installs: unknown[]
let breaks: string[]

beforeEach(() => {
  plans = []
  installs = []
  breaks = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      if (url.pathname.endsWith('/install') && method === 'GET') {
        plans.push(url.searchParams)
        const force = url.searchParams.get('force') === 'true'
        return json({
          steps: [
            {
              item: plugin,
              path: '_civex/plugins/shared_step.py',
              here: 'older',
              local_version: 2,
            },
          ],
          blocked:
            breaks.length && !force ? ['It would break workflows here.'] : [],
          warnings: [],
          breaks,
          runs_code: true,
        })
      }
      if (url.pathname.endsWith('/install') && method === 'POST') {
        installs.push(JSON.parse(String(init?.body)))
        return json({
          steps: [],
          blocked: [],
          warnings: [],
          breaks: [],
          runs_code: true,
        })
      }
      if (url.pathname === '/api/remote/library/plugin/shared_step')
        return json({ ...plugin, content: 'class Plugin: ...' })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(version: number | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LibraryInstallDialog
        kind="plugin"
        name="shared_step"
        version={version}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  )
}

describe('LibraryInstallDialog', () => {
  it('installs plugin code only once the person says they trust it', async () => {
    const user = userEvent.setup()
    renderIt(3)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/Update from v2/)).toBeTruthy()
    expect(plans[0].get('version')).toBe('3')
    const install = within(dialog).getByRole('button', { name: 'Install' })
    expect(install).toHaveProperty('disabled', true)

    await user.click(within(dialog).getByText('Read the code'))
    expect(await within(dialog).findByText('class Plugin: ...')).toBeTruthy()
    await user.click(
      within(dialog).getByText("I've read it and trust whoever published it"),
    )
    await user.click(install)
    await waitFor(() =>
      expect(installs).toEqual([
        { version: 3, replace: false, force: false, with_plugins: true },
      ]),
    )
  })

  it('names what it would break, and installs only if told to anyway', async () => {
    breaks = ["uses-shared: step 'one': config key 'mode' is not allowed"]
    const user = userEvent.setup()
    renderIt()
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/config key 'mode'/)).toBeTruthy()
    await user.click(
      within(dialog).getByText("I've read it and trust whoever published it"),
    )
    const install = within(dialog).getByRole('button', { name: 'Install' })
    expect(install).toHaveProperty('disabled', true)

    await user.click(
      within(dialog).getByText(
        "Install anyway: they won't run until they're fixed",
      ),
    )
    await waitFor(() => expect(install).toHaveProperty('disabled', false))
    await user.click(install)
    await waitFor(() =>
      expect(installs).toEqual([
        { version: null, replace: false, force: true, with_plugins: true },
      ]),
    )
  })
})
