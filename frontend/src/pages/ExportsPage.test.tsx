import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../components/ui/ToastProvider'
import { exported, fakeServer } from '../components/files/testSupport'
import { definition, SCHEMAS } from '../components/exports/exportsTestSupport'
import ExportsPage from './ExportsPage'

afterEach(() => vi.unstubAllGlobals())

function renderAt(url = '/exports') {
  fakeServer({
    '/api/file-access/definitions': [definition()],
    '/api/schemas': SCHEMAS,
    '/api/collections': [],
    '/api/store/volumes': [],
    '/api/file-access/export': exported(),
    '/api/file-access/exports': [
      {
        name: 'hb-Contours',
        location: 'project',
        path: '/proj/_civex/exports/hb-Contours',
        files: 4,
        linked: 4,
        copied: 0,
        bytes_on_disk: 0,
        updated: null,
      },
    ],
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <ExportsPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('the Exports page', () => {
  it('starts on the saved exports', async () => {
    renderAt()

    expect(await screen.findByText('Contours')).toBeInTheDocument()
    expect(screen.queryByText('hb-Contours')).toBeNull()
  })

  it('has the folders made earlier on its own tab', async () => {
    renderAt('/exports?tab=made')

    expect(await screen.findByText('hb-Contours')).toBeInTheDocument()
    expect(screen.queryByText('Contours')).toBeNull()
  })
})
