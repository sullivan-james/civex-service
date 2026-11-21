import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui/ToastProvider'
import { fakeServer, json } from '../components/files/testSupport'
import type { Release } from '../api/releases'
import ReleasesPage from './ReleasesPage'
import ReleasePage from './ReleasePage'
import NewReleasePage from './NewReleasePage'

afterEach(() => vi.unstubAllGlobals())

const RELEASE: Release = {
  id: 'r1',
  name: 'v1',
  title: 'Seal survey',
  description: null,
  authors: [{ name: 'Ada Lovelace', orcid: '0000-0002-1825-0097' }],
  licence: 'CC-BY-4.0',
  doi: '10.1234/abcd',
  keywords: ['seals'],
  scope: {},
  content_hash: 'sha256:' + 'a'.repeat(64),
  bundle_sha256: 'b'.repeat(64),
  bundle_size: 2048,
  counts: { records: 12, schemas: 2, files: 3, file_bytes: 1024 },
  local_seq: 40,
  feed_seq: null,
  civex_version: '1.3.0',
  created_at: '2026-11-21T10:00:00+00:00',
  created_by: 'ada',
  updated_at: null,
  withdrawn_at: null,
  withdrawn_by: null,
  withdrawn_reason: null,
  yanked_at: null,
  yanked_by: null,
  yanked_reason: null,
  file_name: 'release-v1.civex.zip',
  compare_in_background: false,
}

const PLAN = {
  schemas: 2,
  collections: { north: 12 },
  records: 12,
  files: 3,
  file_bytes: 1024,
  by_drive: [{ volume: 'default', files: 3, bytes: 1024 }],
  workflows: 0,
  plugins: 0,
  feed_seq: null,
  local_seq: 40,
  unsent: 0,
}

const CITATION = {
  text: 'Ada Lovelace (2026). Seal survey (Version v1) [Data set].',
  bibtex: '@misc{Lovelace2026v1}',
  cff: 'cff-version: 1.2.0',
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
            <Route path="/releases/new" element={<NewReleasePage />} />
            <Route path="/releases/:name" element={<ReleasePage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return calls
}

describe('the Releases page', () => {
  it('lists releases and links to a page that makes one', async () => {
    renderAt('/releases', { '/api/releases': [RELEASE] })
    expect(await screen.findByText('Seal survey')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New release' })).toHaveAttribute(
      'href',
      '/releases/new',
    )
  })
})

describe('making a release', () => {
  it('plans what it covers, previews the citation, then makes it', async () => {
    const calls = renderAt('/releases/new?records=r1,r2', {
      '/api/releases/plan': PLAN,
      '/api/releases/citation-preview': CITATION,
      '/api/releases': (_b: unknown, method: string) =>
        json(method === 'POST' ? RELEASE : [RELEASE]),
      '/api/collections': [],
    })
    // The explorer's ticked records are what it covers.
    expect(await screen.findByTestId('release-plan')).toHaveTextContent(
      '12 records',
    )
    expect(
      calls.find((c) => c.path === '/api/releases/plan')?.body.records,
    ).toEqual(['r1', 'r2'])
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    const next = screen.getByRole('button', { name: 'Next' })
    expect(next).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText('v1'), {
      target: { value: 'v2' },
    })
    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: 'Second' },
    })
    fireEvent.change(screen.getByPlaceholderText('Ada Lovelace'), {
      target: { value: 'Bo Li' },
    })
    await waitFor(
      () =>
        expect(screen.getByTestId('citation-preview')).toHaveTextContent(
          'Seal survey (Version v1)',
        ),
      { timeout: 2000 },
    )
    fireEvent.click(next)

    expect(await screen.findByText(/Taken at history entry 40/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Make release' }))
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/releases' && c.method === 'POST')
          ?.body,
      ).toMatchObject({
        name: 'v2',
        title: 'Second',
        records: ['r1', 'r2'],
        authors: [{ name: 'Bo Li' }],
      }),
    )
  })
})

describe('a release page', () => {
  it('shows the citation, the manifest and its files', async () => {
    renderAt('/releases/v1', {
      '/api/releases/v1/citation': CITATION,
      '/api/releases/v1/files/plan': {
        total: 3,
        available: 3,
        bytes: 1024,
        available_bytes: 1024,
        complete: true,
        link_volume: 'default',
        by_volume: [],
        summary: 'All 3 files can be reached.',
        unavailable: [],
        tables: [],
        zip_allowed: true,
      },
      '/api/releases/v1': RELEASE,
    })
    expect(
      await screen.findByText(/Seal survey \(Version v1\)/),
    ).toBeInTheDocument()
    expect(screen.getByText(RELEASE.content_hash)).toBeInTheDocument()
    expect(
      await screen.findByText('All 3 files can be reached.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Download as a zip' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'BibTeX' }))
    expect(await screen.findByText('@misc{Lovelace2026v1}')).toBeInTheDocument()
  })

  it('shows a yanked release as its record only', async () => {
    renderAt('/releases/v1', {
      '/api/releases/v1/citation': CITATION,
      '/api/releases/v1': {
        ...RELEASE,
        yanked_at: '2026-11-22T10:00:00+00:00',
        yanked_by: 'ada',
        yanked_reason: 'consent withdrawn',
      },
    })
    expect(await screen.findByText(/consent withdrawn/)).toBeInTheDocument()
    expect(screen.queryByText('Its files')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Download' }),
    ).not.toBeInTheDocument()
  })

  it('compares the release with the data now and opens what each count means', async () => {
    renderAt('/releases/v1?tab=changes', {
      '/api/releases/v1/citation': CITATION,
      '/api/releases/v1/compare': {
        name: 'v1',
        records: 12,
        unchanged: 10,
        added: 1,
        changed: 1,
        removed: 1,
        collections: [
          {
            collection_id: 'c1',
            collection: 'north',
            added: 1,
            changed: 1,
            removed: 1,
            in_scope: true,
          },
        ],
        structure: [
          {
            kind: 'field',
            change: 'changed',
            name: 'site_name',
            schema: 'site',
            what: ['name'],
          },
        ],
        at: 41,
      },
      '/api/releases/v1/compare/records/r9': [
        { field: 'f1', label: 'Depth', dtype: 'float', before: 1, after: 2 },
      ],
      '/api/releases/v1/compare/records': {
        total: 1,
        items: [
          {
            id: 'r9',
            name: 'Seal 9',
            collection: 'north',
            schema: 'seal',
            live: true,
          },
        ],
      },
      '/api/releases/v1': RELEASE,
    })
    expect(
      await screen.findByText(/10 of its 12 records are as they were/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Field site_name of site changed/),
    ).toBeInTheDocument()
    fireEvent.click(screen.getAllByTitle('Show the 1 record changed')[0])
    fireEvent.click(await screen.findByText('Seal 9'))
    expect(await screen.findByText('Depth')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Open the record' }),
    ).toHaveAttribute('href', '/records/r9')
  })

  it('compares a large release only when asked, as a job', async () => {
    const calls = renderAt('/releases/v1?tab=changes', {
      '/api/releases/v1/citation': CITATION,
      '/api/releases/v1': { ...RELEASE, compare_in_background: true },
    })
    expect(
      await screen.findByRole('button', { name: 'Compare with the data now' }),
    ).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/releases/v1/compare')).toBe(false)
  })
})
