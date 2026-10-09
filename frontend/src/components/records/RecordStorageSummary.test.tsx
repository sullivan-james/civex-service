import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui'
import { fakeServer, json, volume } from '../files/testSupport'
import { RecordStorageSummary } from './RecordStorageSummary'

afterEach(() => vi.unstubAllGlobals())

const place = (name: string, kind: string, files: number) => ({
  place: name,
  kind,
  files,
  bytes: files * 1024,
  reason: kind === 'unreachable' ? 'It is not plugged in.' : '',
  fix: '',
})

function show(filesHref?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <RecordStorageSummary
            recordId="enc7"
            name="Encounter 7"
            filesHref={filesHref}
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const listing = (summary: unknown[]) => ({
  total: 1,
  summary,
  items: [],
  kinds: [],
})

describe('RecordStorageSummary', () => {
  it('is silent for a record with no files, with what it contains', async () => {
    const calls = fakeServer({ '/api/file-access/files': listing([]) })
    show()
    await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0))
    expect(
      screen.queryByRole('group', {
        name: "Where this record's files are stored",
      }),
    ).not.toBeInTheDocument()
  })

  it('says where the files of the record and what it contains are', async () => {
    const calls = fakeServer({
      '/api/file-access/files': listing([
        place('archive', 'drive', 10),
        place('field', 'unreachable', 2),
      ]),
    })
    show('?tab=contains&show=files')

    const note = await screen.findByRole('group', {
      name: "Where this record's files are stored",
    })
    expect(note).toHaveTextContent(
      "12 files here and in what it contains: 10 on archive · 2 on field, which can't be reached",
    )
    expect(
      within(note).getByRole('link', { name: 'Show all files' }),
    ).toHaveAttribute('href', '/?tab=contains&show=files')
    expect(calls[0].body).toMatchObject({ within: 'enc7' })
  })

  it('moves them onto a drive with the one move dialog', async () => {
    const calls = fakeServer({
      '/api/file-access/files': listing([place('field', 'drive', 3)]),
      '/api/store/volumes': [volume('field'), volume('archive')],
      '/api/file-access/gather': () =>
        json({
          plan: {
            files: 3,
            bytes: 3072,
            from_server: 0,
            already_there: 0,
            copied: 1,
            repointed: 0,
            freed_bytes: 2048,
          },
        }),
      '/api/remote': { configured: false },
    })
    show()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Move to drive…' }),
    )
    expect(
      await screen.findByText(
        /Copies 3 files there .* 1 stay where they are too/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/Frees 2.0 KB on other drives/)).toBeInTheDocument()
    const preview = calls.find((c) => c.path === '/api/file-access/gather')
    expect(preview?.body).toMatchObject({ within: 'enc7', volume: 'archive' })
  })
})
