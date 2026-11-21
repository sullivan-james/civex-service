import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui/ToastProvider'
import { fakeServer, json } from '../components/files/testSupport'
import type { Release } from '../api/releases'
import ReleasesPage from './ReleasesPage'
import ReleasePage from './ReleasePage'

afterEach(() => vi.unstubAllGlobals())

const RELEASE: Release = {
  id: 'r1',
  name: 'v1',
  title: 'Seal survey',
  description: null,
  authors: ['Ada Lovelace'],
  licence: 'CC-BY-4.0',
  doi: '10.1234/abcd',
  scope: {},
  include_files: true,
  content_hash: 'sha256:' + 'a'.repeat(64),
  bundle_sha256: 'b'.repeat(64),
  bundle_size: 2048,
  counts: { records: 12, schemas: 2, files_carried: 3, file_bytes: 1024 },
  local_seq: 40,
  feed_seq: null,
  civex_version: '1.3.0',
  created_at: '2026-11-21T10:00:00+00:00',
  created_by: 'ada',
  updated_at: null,
  withdrawn_at: null,
  withdrawn_by: null,
  withdrawn_reason: null,
  file_name: 'release-v1.civex.zip',
}

const PLAN = {
  schemas: 2,
  collections: ['north'],
  records: 12,
  files: 3,
  file_bytes: 1024,
  files_unreachable: 0,
  workflows: 0,
  plugins: 0,
  include_files: true,
}

function renderAt(url: string, routes: Record<string, unknown>) {
  const calls = fakeServer(routes as never)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route path="/releases" element={<ReleasesPage />} />
            <Route path="/releases/:name" element={<ReleasePage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return calls
}

describe('the Releases page', () => {
  it('lists releases and plans a new one before making it', async () => {
    const calls = renderAt('/releases', {
      '/api/releases': (_b: unknown, method: string) =>
        json(method === 'POST' ? RELEASE : [RELEASE]),
      '/api/releases/plan': PLAN,
      '/api/collections': [],
    })
    expect(await screen.findByText('Seal survey')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'New release' }))
    expect(await screen.findByTestId('release-plan')).toHaveTextContent(
      '12 records',
    )
    const make = screen.getByRole('button', { name: 'Make release' })
    expect(make).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText('v1'), {
      target: { value: 'v2' },
    })
    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: 'Second' },
    })
    fireEvent.click(make)
    await waitFor(() =>
      expect(
        calls.some((c) => c.path === '/api/releases' && c.method === 'POST'),
      ).toBe(true),
    )
  })
})

describe('a release page', () => {
  it('shows the citation, the manifest and what changed since', async () => {
    renderAt('/releases/v1', {
      '/api/releases/v1': RELEASE,
      '/api/releases/v1/citation': {
        text: 'Ada Lovelace (2026). Seal survey (Version v1) [Data set].',
        bibtex: '@misc{Lovelace2026v1}',
        cff: 'cff-version: 1.2.0',
      },
    })
    expect(
      await screen.findByText(/Seal survey \(Version v1\)/),
    ).toBeInTheDocument()
    expect(screen.getByText(RELEASE.content_hash)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'BibTeX' }))
    expect(await screen.findByText('@misc{Lovelace2026v1}')).toBeInTheDocument()
  })
})
