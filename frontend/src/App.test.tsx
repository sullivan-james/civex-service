import { describe, expect, it, afterEach, beforeAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import App from './App'
import { fakeServer } from './components/files/testSupport'
import { ThemeProvider } from './hooks/useTheme'
import { ToastProvider } from './components/ui/ToastProvider'
import { localFeatures } from './utils/features'

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia
})

afterEach(() => {
  delete window.__CIVEX__
})

/** The whole app at `path`, on a server that offers every feature but `off`. */
function renderApp(
  path: string,
  off: string[] = [],
  routes: Record<string, unknown> = {},
) {
  fakeServer({
    '/api/status/features': {
      features: [...localFeatures].filter((f) => !off.includes(f)),
      all: {},
    },
    '/api/collections': [],
    '/api/store/transfers': [],
    '/api/settings/ui': { show_advanced: false },
    '/api/retention/purged-history': { entries: 0 },
    '/api/settings/retention': {
      purge_after_days: 30,
      auto_purge_deleted: false,
      audit_days: null,
      run_days: null,
    },
    ...routes,
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

const blocked = () => screen.findByText('Not available here', { selector: 'p' })

describe('a page whose feature the server turned off', () => {
  it.each([
    ['/terminal', 'terminal'],
    ['/ai', 'ai'],
    ['/plugins', 'plugin_editor'],
    ['/plugins/new', 'plugin_editor'],
    ['/workflows', 'local_workflows'],
    ['/workflows/new', 'local_workflows'],
    ['/runs', 'local_workflows'],
    ['/settings/storage/volumes/main', 'volumes'],
    ['/settings/database', 'db_admin'],
    ['/settings/storage', 'store_admin'],
    ['/settings/updates', 'updates'],
    ['/settings/logs', 'logs'],
    ['/settings/appearance', 'settings_appearance'],
    ['/settings/retention', 'settings_retention'],
    ['/settings/map', 'settings_map'],
    ['/settings/advanced', 'settings_advanced'],
  ])('is blocked at %s without %s', async (path, feature) => {
    renderApp(path, [feature])
    expect(await blocked()).toBeInTheDocument()
  })

  it('blocks Members & access without either feature behind it', async () => {
    renderApp('/settings/members', ['settings_members'])
    expect(await blocked()).toBeInTheDocument()
  })

  it('hides all of Settings with the umbrella feature', async () => {
    renderApp('/settings/map', ['settings'])
    expect(await blocked()).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Settings' })).toBeNull()
  })

  it('leaves the other settings sections, and opens the first left on', async () => {
    renderApp('/settings', [
      'settings_appearance',
      'settings_map',
      'db_admin',
      'store_admin',
    ])
    // Until the server answers, a local civex is assumed: wait for it.
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Retention' })).toHaveAttribute(
        'aria-current',
        'page',
      ),
    )
    const nav = screen.getByRole('navigation', { name: 'Settings sections' })
    const names = Array.from(nav.querySelectorAll('a')).map(
      (a) => a.textContent,
    )
    expect(names).not.toContain('Appearance')
    expect(names).not.toContain('Map')
    expect(names).not.toContain('Database')
  })

  it('is hidden from the navigation too', async () => {
    renderApp('/collections', ['terminal', 'plugin_editor', 'local_workflows'])
    await screen.findByRole('navigation', { name: 'Primary' })
    // Until the server answers a local civex is assumed, so wait for it.
    await waitFor(() =>
      expect(screen.queryByRole('link', { name: 'Workflows' })).toBeNull(),
    )
    expect(screen.queryByRole('link', { name: 'Terminal' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Plugins' })).toBeNull()
  })
})

describe('everything on, as on a desktop', () => {
  it('shows Settings and its first section', async () => {
    renderApp('/settings')
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Appearance' })).toHaveAttribute(
        'aria-current',
        'page',
      ),
    )
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.queryByText('Not available here')).toBeNull()
  })
})

const remote = (extra: Record<string, unknown>) => ({
  '/api/remote': { configured: true, serving: false, pending: 0, ...extra },
  '/api/remote/conflicts': [],
})

describe('the sync review and the sync button', () => {
  it('are not for a project that follows nothing', async () => {
    renderApp('/sync/review', [], remote({ configured: false }))
    expect(await blocked()).toBeInTheDocument()
  })

  it('are not for a hosted authority', async () => {
    renderApp('/sync/review', [], remote({ serving: true }))
    expect(await blocked()).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sync/i })).toBeNull()
  })

  it('are there for a project that follows a remote', async () => {
    renderApp('/sync/review', [], remote({}))
    await screen.findByRole('navigation', { name: 'Primary' })
    expect(screen.queryByText('Not available here')).toBeNull()
  })
})
