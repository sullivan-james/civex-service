import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ToastProvider } from '../components/ui/ToastProvider'
import { fakeServer, json } from '../components/files/testSupport'
import { definition, SCHEMAS } from '../components/exports/exportsTestSupport'
import ExportEditorPage from './ExportEditorPage'

afterEach(() => vi.unstubAllGlobals())

function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

function renderAt(url: string, entries: string[] = [url]) {
  const calls = fakeServer({
    '/api/schemas': SCHEMAS,
    '/api/schemas/encounter/exports': (
      _body: Record<string, unknown>,
      method: string,
    ) => (method === 'POST' ? json(definition(), 201) : json([definition()])),
    '/api/schemas/encounter/exports/Contours': () => json(definition()),
    '/api/file-access/plan': () => json({ total: 0, items: [], tables: [] }),
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={entries}
          initialIndex={entries.length - 1}
        >
          <Routes>
            <Route path="/exports" element={<Where />} />
            <Route path="/exports/new" element={<ExportEditorPage />} />
            <Route
              path="/exports/:schema/:name"
              element={<ExportEditorPage />}
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return calls
}

describe('an export on its own page', () => {
  it('is a new export at /exports/new, starting from the first kind', async () => {
    renderAt('/exports/new')

    expect(
      await screen.findByRole('heading', { name: 'New export' }),
    ).toBeInTheDocument()
    expect(
      (screen.getByLabelText('Starts from') as HTMLSelectElement).value,
    ).toBe('encounter')
  })

  it('starts from the kind asked for in the address', async () => {
    renderAt('/exports/new?schema=recording')

    expect(
      ((await screen.findByLabelText('Starts from')) as HTMLSelectElement)
        .value,
    ).toBe('recording')
  })

  it('is an existing export at /exports/<schema>/<name>, filled in, with its kind fixed', async () => {
    renderAt('/exports/encounter/Contours')

    expect(
      await screen.findByRole('heading', { name: 'Contours' }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Starts from')).toBeNull()
    expect(screen.getByText('Starts from')).toBeInTheDocument()
  })

  it('has breadcrumbs back to the list', async () => {
    renderAt('/exports/encounter/Contours')

    expect(
      await screen.findByRole('link', { name: 'Exports' }),
    ).toHaveAttribute('href', '/exports')
  })

  it('says so when the export is not there', async () => {
    renderAt('/exports/encounter/Gone')

    expect(
      await screen.findByText('That export is not here'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Back to exports' }),
    ).toHaveAttribute('href', '/exports')
  })

  it('cancels back to where the person came from', async () => {
    renderAt('/exports/new', ['/exports?q=sheets', '/exports/new'])
    await screen.findByRole('heading', { name: 'New export' })

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(
        '/exports?q=sheets',
      ),
    )
  })

  it('saves, then goes back too', async () => {
    const calls = renderAt('/exports/encounter/Contours', [
      '/exports',
      '/exports/encounter/Contours',
    ])
    await screen.findByRole('heading', { name: 'Contours' })

    await userEvent.click(screen.getByRole('button', { name: /^next/i }))
    await userEvent.click(screen.getByRole('button', { name: /^next/i }))
    await userEvent.click(
      screen.getByRole('button', { name: /^save changes$/i }),
    )

    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('/exports'),
    )
    expect(calls.some((c) => c.method === 'PATCH')).toBe(true)
  })
})
